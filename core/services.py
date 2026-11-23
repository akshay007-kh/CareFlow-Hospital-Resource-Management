"""Atomic resource operations and their business rules."""
from django.db import IntegrityError, transaction
from django.db.models import F
from django.utils import timezone
from .models import (ActivityLog, Bed, BedAllocation, Patient, Equipment,
                     EquipmentRequest, EquipmentAllocation, Medicine, StockTransaction)


class ResourceError(ValueError):
    pass


def log(actor, action):
    ActivityLog.objects.create(actor=actor, action=action[:180])


@transaction.atomic
def allocate_bed(patient_id, bed_id, actor):
    patient = Patient.objects.select_for_update().get(pk=patient_id)
    bed = Bed.objects.select_for_update().get(pk=bed_id)
    if patient.status == Patient.Status.DISCHARGED:
        raise ResourceError('Discharged patients cannot receive new bed allocations.')
    if not bed.is_active or bed.under_maintenance:
        raise ResourceError('This bed is not available for allocation.')
    if BedAllocation.objects.filter(bed=bed, released_at__isnull=True).exists():
        raise ResourceError('This bed is already occupied.')
    if BedAllocation.objects.filter(patient=patient, released_at__isnull=True).exists():
        raise ResourceError('This patient already has an assigned bed.')
    try:
        allocation = BedAllocation.objects.create(bed=bed, patient=patient, allocated_by=actor)
    except IntegrityError as exc:
        raise ResourceError('That bed or patient was allocated by another request. Refresh and try again.') from exc
    patient.status = Patient.Status.ADMITTED
    patient.admission_date = patient.admission_date or timezone.now()
    patient.discharged_at = None
    patient.save(update_fields=['status', 'admission_date', 'discharged_at'])
    log(actor, f'Allocated bed {bed.number} to {patient.full_name}')
    return allocation


@transaction.atomic
def release_bed(allocation_id, actor):
    allocation = BedAllocation.objects.select_for_update().select_related('patient', 'bed').get(pk=allocation_id)
    if allocation.released_at:
        raise ResourceError('This bed has already been released.')
    allocation.released_at = timezone.now()
    allocation.save(update_fields=['released_at'])
    log(actor, f'Released bed {allocation.bed.number} for {allocation.patient.full_name}')
    return allocation


@transaction.atomic
def discharge_patient(patient_id, actor):
    patient = Patient.objects.select_for_update().get(pk=patient_id)
    if patient.status != Patient.Status.ADMITTED:
        raise ResourceError('Only admitted patients can be discharged.')
    if EquipmentAllocation.objects.filter(patient=patient, returned_at__isnull=True).exists():
        raise ResourceError('Return all issued equipment before discharging the patient.')
    BedAllocation.objects.filter(patient=patient, released_at__isnull=True).update(released_at=timezone.now())
    patient.status = Patient.Status.DISCHARGED
    patient.discharged_at = timezone.now()
    patient.save(update_fields=['status', 'discharged_at'])
    log(actor, f'Discharged {patient.full_name}')


@transaction.atomic
def review_equipment_request(request_id, actor, action):
    req = EquipmentRequest.objects.select_for_update().select_related('equipment', 'patient').get(pk=request_id)
    if action in ('approve', 'reject'):
        if req.status != EquipmentRequest.Status.PENDING:
            raise ResourceError('Only pending requests can be reviewed.')
        req.status = EquipmentRequest.Status.APPROVED if action == 'approve' else EquipmentRequest.Status.REJECTED
        req.reviewed_by = actor
        req.save(update_fields=['status', 'reviewed_by', 'updated_at'])
        log(actor, f'{"Approved" if action == "approve" else "Rejected"} equipment request #{req.pk}')
        return
    if action != 'fulfill' or req.status != EquipmentRequest.Status.APPROVED:
        raise ResourceError('Only approved requests can be issued.')
    if req.patient.status == Patient.Status.DISCHARGED:
        raise ResourceError('Cannot issue equipment to a discharged patient.')
    item = Equipment.objects.select_for_update().get(pk=req.equipment_id)
    if item.condition != Equipment.Condition.READY or item.available_quantity < req.quantity:
        raise ResourceError('Equipment is unavailable or has insufficient quantity.')
    # Conditional update guards against a stock race even on SQLite.
    changed = Equipment.objects.filter(pk=item.pk, condition=Equipment.Condition.READY,
                                       available_quantity__gte=req.quantity).update(available_quantity=F('available_quantity') - req.quantity)
    if not changed:
        raise ResourceError('Equipment quantity changed; refresh and retry.')
    EquipmentAllocation.objects.create(request=req, equipment=item, patient=req.patient, quantity=req.quantity, issued_by=actor)
    req.status = EquipmentRequest.Status.FULFILLED
    req.save(update_fields=['status', 'updated_at'])
    log(actor, f'Issued {req.quantity} × {item.name} for {req.patient.full_name}')


@transaction.atomic
def return_equipment(allocation_id, actor):
    allocation = EquipmentAllocation.objects.select_for_update().select_related('equipment').get(pk=allocation_id)
    if allocation.returned_at:
        raise ResourceError('Equipment was already returned.')
    Equipment.objects.filter(pk=allocation.equipment_id).update(available_quantity=F('available_quantity') + allocation.quantity)
    allocation.returned_at = timezone.now()
    allocation.save(update_fields=['returned_at'])
    log(actor, f'Returned {allocation.quantity} × {allocation.equipment.name}')


@transaction.atomic
def adjust_equipment(equipment_id, delta, actor):
    item = Equipment.objects.select_for_update().get(pk=equipment_id)
    if delta == 0:
        raise ResourceError('Enter a non-zero adjustment.')
    new_total = item.total_quantity + delta
    new_available = item.available_quantity + delta
    if new_total < 0 or new_available < 0:
        raise ResourceError('Cannot remove more than the available equipment quantity.')
    item.total_quantity = new_total
    item.available_quantity = new_available
    item.save(update_fields=['total_quantity', 'available_quantity'])
    log(actor, f'Adjusted {item.name} quantity by {delta:+d}')


@transaction.atomic
def move_stock(medicine_id, direction, quantity, actor, note=''):
    if quantity < 1 or direction not in (StockTransaction.Direction.IN, StockTransaction.Direction.OUT):
        raise ResourceError('Select a valid direction and a positive quantity.')
    medicine = Medicine.objects.select_for_update().get(pk=medicine_id)
    if direction == StockTransaction.Direction.OUT:
        if medicine.is_expired:
            raise ResourceError('Expired medicine cannot be issued.')
        updated = Medicine.objects.filter(pk=medicine.pk, stock__gte=quantity).update(stock=F('stock') - quantity)
        if not updated:
            raise ResourceError('Insufficient medicine stock.')
    else:
        Medicine.objects.filter(pk=medicine.pk).update(stock=F('stock') + quantity)
    record = StockTransaction.objects.create(medicine=medicine, direction=direction, quantity=quantity,
                                             performed_by=actor, note=note)
    log(actor, f'{direction.upper()} {quantity} {medicine.unit} of {medicine.name}')
    return record
