from functools import wraps
from django.contrib import messages
from django.contrib.auth import login as auth_login, logout as auth_logout
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q, F
from django.http import Http404, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST
from django.core.paginator import Paginator
from django.utils import timezone
from .forms import (RegistrationForm, LoginForm, DepartmentForm, UserEditForm, PatientForm,
                    PatientSelfForm, TreatmentForm, BedForm, BedAllocationForm,
                    EquipmentCreateForm, EquipmentEditForm, EquipmentAdjustmentForm,
                    EquipmentRequestForm, MedicineCreateForm, MedicineEditForm,
                    StockMovementForm, FeedbackForm)
from .models import (User, Department, Patient, Bed, BedAllocation, Equipment,
                     EquipmentRequest, EquipmentAllocation, Medicine,
                     StockTransaction, Feedback, ActivityLog)
from .services import (ResourceError, allocate_bed, release_bed, discharge_patient,
                       review_equipment_request, return_equipment, adjust_equipment,
                       move_stock, log)


def role_of(user):
    return User.Role.ADMIN if user.is_superuser else user.role


def roles_required(*roles):
    def decorate(view):
        @login_required
        @wraps(view)
        def guard(request, *args, **kwargs):
            if role_of(request.user) not in roles or not request.user.is_approved:
                return render(request, 'forbidden.html', status=403)
            return view(request, *args, **kwargs)
        return guard
    return decorate


def paginate(request, queryset, size=10):
    return Paginator(queryset, size).get_page(request.GET.get('page'))


def form_page(request, form_type, title, subtitle, cancel_url, instance=None, on_save=None):
    form = form_type(request.POST or None, instance=instance) if instance is not None else form_type(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        result = form.save()
        if on_save:
            on_save(result)
        messages.success(request, f'{title} saved successfully.')
        return redirect(cancel_url)
    return render(request, 'form_page.html', {'form': form, 'page_title': title,
                  'page_subtitle': subtitle, 'cancel_url': cancel_url})


def home(request):
    if request.user.is_authenticated:
        return redirect('dashboard')
    return render(request, 'home.html')


def register(request):
    if request.user.is_authenticated:
        return redirect('dashboard')
    form = RegistrationForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        user = form.save()
        if user.is_approved:
            messages.success(request, 'Account created! You can now sign in.')
        else:
            messages.success(request, 'Registration received. Your hospital administrator must approve your account before login.')
        return redirect('login')
    return render(request, 'register.html', {'form': form})


def login_view(request):
    if request.user.is_authenticated:
        return redirect('dashboard')
    form = LoginForm(request=request, data=request.POST or None)
    if request.method == 'POST' and form.is_valid():
        auth_login(request, form.get_user())
        messages.success(request, f'Welcome back, {request.user.display_name}!')
        return redirect('dashboard')
    return render(request, 'login.html', {'form': form})


@require_POST
@login_required
def logout_view(request):
    auth_logout(request)
    messages.info(request, 'You have signed out.')
    return redirect('home')


@login_required
def dashboard(request):
    if not request.user.is_approved and not request.user.is_superuser:
        auth_logout(request)
        messages.warning(request, 'Your account is still awaiting approval.')
        return redirect('login')
    role = role_of(request.user)
    return redirect({'admin': 'admin_dashboard', 'doctor': 'doctor_dashboard',
                     'staff': 'staff_dashboard', 'patient': 'patient_dashboard'}.get(role, 'home'))


def bed_statistics():
    active = Bed.objects.filter(is_active=True, under_maintenance=False)
    used = BedAllocation.objects.filter(released_at__isnull=True, bed__in=active).count()
    return {'beds_total': active.count(), 'beds_occupied': used, 'beds_available': active.count() - used}


@roles_required('admin')
def admin_dashboard(request):
    stats = bed_statistics()
    stats.update(patients=Patient.objects.count(), admitted=Patient.objects.filter(status='admitted').count(),
                 doctors=User.objects.filter(role='doctor', is_approved=True, is_active=True).count(),
                 pending_users=User.objects.filter(role__in=['doctor', 'staff'], is_approved=False, is_active=True).count(),
                 pending_equipment=EquipmentRequest.objects.filter(status='pending').count(),
                 medicines_low=Medicine.objects.filter(stock__lte=F('minimum_stock')).count())
    return render(request, 'admin_dashboard.html', {'stats': stats,
        'recent_patients': Patient.objects.select_related('assigned_doctor')[:6],
        'activities': ActivityLog.objects.select_related('actor')[:7],
        'recent_requests': EquipmentRequest.objects.select_related('equipment', 'patient')[:5]})


@roles_required('doctor')
def doctor_dashboard(request):
    patients = Patient.objects.filter(assigned_doctor=request.user)
    return render(request, 'doctor_dashboard.html', {'stats': {**bed_statistics(),
        'patients': patients.count(), 'admitted': patients.filter(status='admitted').count(),
        'pending_equipment': EquipmentRequest.objects.filter(requested_by=request.user, patient__assigned_doctor=request.user, status='pending').count()},
        'recent_patients': patients[:7],
        'recent_requests': EquipmentRequest.objects.filter(requested_by=request.user, patient__assigned_doctor=request.user).select_related('equipment', 'patient')[:5]})


@roles_required('staff')
def staff_dashboard(request):
    return render(request, 'staff_dashboard.html', {'stats': {**bed_statistics(),
        'patients': Patient.objects.count(), 'admitted': Patient.objects.filter(status='admitted').count(),
        'medicines_low': Medicine.objects.filter(stock__lte=F('minimum_stock')).count(),
        'approved_equipment': EquipmentRequest.objects.filter(status='approved').count()},
        'recent_patients': Patient.objects.select_related('assigned_doctor')[:7],
        'recent_requests': EquipmentRequest.objects.filter(status='approved').select_related('equipment', 'patient')[:5]})


@roles_required('patient')
def patient_dashboard(request):
    patient = Patient.objects.filter(user=request.user).select_related('assigned_doctor').first()
    allocation = BedAllocation.objects.filter(patient=patient, released_at__isnull=True).select_related('bed').first() if patient else None
    issued_equipment = EquipmentAllocation.objects.filter(patient=patient, returned_at__isnull=True).select_related('equipment') if patient else []
    return render(request, 'patient_dashboard.html', {'patient': patient, 'allocation': allocation,
                                                       'issued_equipment': issued_equipment,
                                                       'feedback_count': Feedback.objects.filter(patient=request.user).count()})


@roles_required('admin')
def users(request):
    records = User.objects.exclude(is_superuser=True).select_related('department').order_by('-date_joined')
    q = request.GET.get('q', '').strip()
    role = request.GET.get('role', '')
    if q:
        records = records.filter(Q(username__icontains=q) | Q(first_name__icontains=q) |
                                 Q(last_name__icontains=q) | Q(email__icontains=q))
    if role in ('doctor', 'staff', 'patient'):
        records = records.filter(role=role)
    return render(request, 'users.html', {'items': paginate(request, records), 'query': q, 'role_filter': role})


@require_POST
@roles_required('admin')
def user_approval(request, pk):
    person = get_object_or_404(User, pk=pk, role__in=['doctor', 'staff'], is_superuser=False)
    person.is_approved = not person.is_approved
    person.save(update_fields=['is_approved'])
    log(request.user, f'{"Approved" if person.is_approved else "Revoked"} access for {person.username}')
    messages.success(request, 'User approval updated.')
    return redirect('users')


@roles_required('admin')
def user_edit(request, pk):
    person = get_object_or_404(User, pk=pk, is_superuser=False)
    return form_page(request, UserEditForm, f'Edit {person.username}', 'Manage account information and access.',
                     reverse('users'), instance=person, on_save=lambda u: log(request.user, f'Updated account {u.username}'))


@roles_required('admin')
def departments(request):
    return render(request, 'departments.html', {'items': Department.objects.annotate(staff_count=Count('user')).all()})


@roles_required('admin')
def department_new(request):
    return form_page(request, DepartmentForm, 'Add department', 'Create a hospital department.', reverse('departments'))


@roles_required('admin')
def department_edit(request, pk):
    dept = get_object_or_404(Department, pk=pk)
    return form_page(request, DepartmentForm, 'Edit department', 'Update department information.', reverse('departments'), instance=dept)


@roles_required('admin', 'staff', 'doctor')
def patients(request):
    records = Patient.objects.select_related('assigned_doctor')
    if role_of(request.user) == 'doctor':
        records = records.filter(assigned_doctor=request.user)
    q = request.GET.get('q', '').strip()
    status = request.GET.get('status', '')
    if q:
        records = records.filter(Q(full_name__icontains=q) | Q(diagnosis__icontains=q) | Q(phone__icontains=q))
    if status in ('waiting', 'admitted', 'discharged'):
        records = records.filter(status=status)
    return render(request, 'patients.html', {'items': paginate(request, records), 'query': q, 'status_filter': status})


@roles_required('admin', 'staff', 'doctor', 'patient')
def patient_detail(request, pk):
    patient = get_object_or_404(Patient.objects.select_related('assigned_doctor', 'user'), pk=pk)
    role = role_of(request.user)
    if (role == 'doctor' and patient.assigned_doctor_id != request.user.pk) or (role == 'patient' and patient.user_id != request.user.pk):
        return render(request, 'forbidden.html', status=403)
    bed = BedAllocation.objects.filter(patient=patient, released_at__isnull=True).select_related('bed').first()
    equipment = EquipmentAllocation.objects.filter(patient=patient, returned_at__isnull=True).select_related('equipment')
    return render(request, 'patient_detail.html', {'patient': patient, 'bed_assignment': bed, 'equipment_items': equipment})


@roles_required('admin', 'staff')
def patient_new(request):
    return form_page(request, PatientForm, 'Register patient', 'Create a new patient record.', reverse('patients'),
                     on_save=lambda p: log(request.user, f'Created patient {p.full_name}'))


@roles_required('admin', 'staff')
def patient_edit(request, pk):
    patient = get_object_or_404(Patient, pk=pk)
    return form_page(request, PatientForm, 'Edit patient', 'Update patient and doctor details.', reverse('patient_detail', args=[pk]),
                     instance=patient, on_save=lambda p: log(request.user, f'Updated patient {p.full_name}'))


@require_POST
@roles_required('admin')
def patient_delete(request, pk):
    patient = get_object_or_404(Patient, pk=pk)
    from django.db.models.deletion import ProtectedError
    try:
        name = patient.full_name
        patient.delete()
        log(request.user, f'Deleted patient {name}')
        messages.success(request, 'Patient removed.')
    except ProtectedError:
        messages.error(request, 'This patient has resource history. Keep the record for audit purposes.')
    return redirect('patients')


@require_POST
@roles_required('admin', 'staff')
def patient_discharge(request, pk):
    try:
        discharge_patient(pk, request.user)
        messages.success(request, 'Patient discharged and bed released successfully.')
    except ResourceError as exc:
        messages.error(request, str(exc))
    return redirect('patient_detail', pk=pk)


@roles_required('doctor')
def doctor_treatment(request, pk):
    patient = get_object_or_404(Patient, pk=pk, assigned_doctor=request.user)
    return form_page(request, TreatmentForm, 'Update treatment', 'Medical notes are only accessible to authorized hospital users.',
                     reverse('patient_detail', args=[pk]), instance=patient,
                     on_save=lambda p: log(request.user, f'Updated clinical notes for {p.full_name}'))


@roles_required('patient')
def patient_profile(request):
    patient, _ = Patient.objects.get_or_create(user=request.user,
        defaults={'full_name': request.user.display_name, 'phone': request.user.phone})
    return form_page(request, PatientSelfForm, 'My profile', 'Update your demographic and contact details.',
                     reverse('patient_dashboard'), instance=patient)


@roles_required('admin', 'staff', 'doctor')
def beds(request):
    records = Bed.objects.all()
    q = request.GET.get('q', '').strip()
    if q:
        records = records.filter(Q(number__icontains=q) | Q(ward__icontains=q))
    return render(request, 'beds.html', {'items': paginate(request, records, 16), 'query': q,
                                        'recent_allocations': (BedAllocation.objects.filter(released_at__isnull=True).select_related('patient', 'bed')[:10] if role_of(request.user) != 'doctor' else [])})


@roles_required('admin')
def bed_new(request):
    return form_page(request, BedForm, 'Add hospital bed', 'Create an available bed in a ward.', reverse('beds'))


@roles_required('admin')
def bed_edit(request, pk):
    bed = get_object_or_404(Bed, pk=pk)
    return form_page(request, BedForm, 'Edit hospital bed', 'Change ward, floor, or maintenance status.', reverse('beds'), instance=bed)


@roles_required('admin', 'staff')
def bed_assign(request):
    form = BedAllocationForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        try:
            allocate_bed(form.cleaned_data['patient'].pk, form.cleaned_data['bed'].pk, request.user)
            messages.success(request, 'Bed allocated and patient marked as admitted.')
            return redirect('beds')
        except ResourceError as exc:
            form.add_error(None, str(exc))
    return render(request, 'form_page.html', {'form': form, 'page_title': 'Allocate bed',
                   'page_subtitle': 'Choose a registered patient and an available bed.', 'cancel_url': reverse('beds')})


@require_POST
@roles_required('admin', 'staff')
def bed_release(request, pk):
    try:
        release_bed(pk, request.user)
        messages.success(request, 'Bed released. Patient remains admitted until discharged.')
    except ResourceError as exc:
        messages.error(request, str(exc))
    return redirect('beds')


@roles_required('admin', 'staff', 'doctor')
def equipment(request):
    records = Equipment.objects.all()
    q = request.GET.get('q', '').strip()
    if q:
        records = records.filter(Q(name__icontains=q) | Q(code__icontains=q) | Q(category__icontains=q))
    return render(request, 'equipment.html', {'items': paginate(request, records), 'query': q})


@roles_required('admin')
def equipment_new(request):
    return form_page(request, EquipmentCreateForm, 'Add equipment', 'Register a new medical resource.', reverse('equipment'))


@roles_required('admin')
def equipment_edit(request, pk):
    obj = get_object_or_404(Equipment, pk=pk)
    return form_page(request, EquipmentEditForm, 'Edit equipment', 'Manage item details and operational condition.', reverse('equipment'), instance=obj)


@roles_required('admin')
def equipment_adjust(request, pk):
    obj = get_object_or_404(Equipment, pk=pk)
    form = EquipmentAdjustmentForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        try:
            adjust_equipment(obj.pk, form.cleaned_data['delta'], request.user)
            messages.success(request, 'Equipment quantity adjusted.')
            return redirect('equipment')
        except ResourceError as exc:
            form.add_error(None, str(exc))
    return render(request, 'form_page.html', {'form': form, 'page_title': f'Adjust {obj.name}',
                   'page_subtitle': f'Current total: {obj.total_quantity}, available: {obj.available_quantity}.',
                   'cancel_url': reverse('equipment')})


@roles_required('admin', 'staff', 'doctor')
def equipment_requests(request):
    records = EquipmentRequest.objects.select_related('requested_by', 'patient', 'equipment')
    if role_of(request.user) == 'doctor':
        records = records.filter(requested_by=request.user, patient__assigned_doctor=request.user)
    status = request.GET.get('status', '')
    if status in ('pending', 'approved', 'rejected', 'fulfilled'):
        records = records.filter(status=status)
    return render(request, 'equipment_requests.html', {'items': paginate(request, records), 'status_filter': status})


@roles_required('doctor')
def equipment_request_new(request):
    form = EquipmentRequestForm(request.POST or None, doctor=request.user)
    if request.method == 'POST' and form.is_valid():
        obj = form.save(commit=False)
        obj.requested_by = request.user
        obj.save()
        log(request.user, f'Requested {obj.quantity} × {obj.equipment.name}')
        messages.success(request, 'Request submitted to the hospital administrator.')
        return redirect('equipment_requests')
    return render(request, 'form_page.html', {'form': form, 'page_title': 'Request equipment',
                   'page_subtitle': 'Request a resource for one of your assigned patients.',
                   'cancel_url': reverse('equipment_requests')})


@require_POST
@roles_required('admin', 'staff')
def equipment_request_action(request, pk):
    action = request.POST.get('action', '')
    if action in ('approve', 'reject') and role_of(request.user) != 'admin':
        return render(request, 'forbidden.html', status=403)
    try:
        review_equipment_request(pk, request.user, action)
        messages.success(request, 'Equipment request updated.')
    except ResourceError as exc:
        messages.error(request, str(exc))
    return redirect('equipment_requests')


@roles_required('admin', 'staff')
def equipment_allocations(request):
    records = EquipmentAllocation.objects.select_related('patient', 'equipment', 'request')
    return render(request, 'equipment_allocations.html', {'items': paginate(request, records)})


@require_POST
@roles_required('admin', 'staff')
def equipment_return(request, pk):
    try:
        return_equipment(pk, request.user)
        messages.success(request, 'Equipment returned to available stock.')
    except ResourceError as exc:
        messages.error(request, str(exc))
    return redirect('equipment_allocations')


@roles_required('admin', 'staff')
def medicines(request):
    records = Medicine.objects.all()
    q = request.GET.get('q', '').strip()
    if q:
        records = records.filter(Q(name__icontains=q) | Q(sku__icontains=q))
    return render(request, 'medicines.html', {'items': paginate(request, records), 'query': q,
        'transactions': StockTransaction.objects.select_related('medicine', 'performed_by')[:6]})


@roles_required('admin')
def medicine_new(request):
    return form_page(request, MedicineCreateForm, 'Add medicine', 'Create an item in pharmacy inventory.', reverse('medicines'))


@roles_required('admin')
def medicine_edit(request, pk):
    obj = get_object_or_404(Medicine, pk=pk)
    return form_page(request, MedicineEditForm, 'Edit medicine', 'Use a stock movement to change quantities.', reverse('medicines'), instance=obj)


@roles_required('admin', 'staff')
def medicine_stock(request, pk):
    obj = get_object_or_404(Medicine, pk=pk)
    form = StockMovementForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        try:
            move_stock(obj.pk, form.cleaned_data['direction'], form.cleaned_data['quantity'], request.user, form.cleaned_data['note'])
            messages.success(request, 'Medicine stock updated and transaction recorded.')
            return redirect('medicines')
        except ResourceError as exc:
            form.add_error(None, str(exc))
    return render(request, 'form_page.html', {'form': form, 'page_title': f'Move stock · {obj.name}',
                   'page_subtitle': f'Currently in stock: {obj.stock} {obj.unit}.', 'cancel_url': reverse('medicines')})


@roles_required('admin')
def reports(request):
    stats = bed_statistics()
    stats.update(patients_total=Patient.objects.count(), admissions=Patient.objects.filter(status='admitted').count(),
                 doctors=User.objects.filter(role='doctor', is_approved=True).count(),
                 equipment_total=Equipment.objects.count(),
                 requests_pending=EquipmentRequest.objects.filter(status='pending').count(),
                 low_stock=Medicine.objects.filter(stock__lte=F('minimum_stock')).count(),
                 expired=Medicine.objects.filter(expiry_date__lt=timezone.localdate()).count())
    wards = Bed.objects.values('ward').annotate(total=Count('id')).order_by('ward')
    summary = Patient.objects.values('status').annotate(total=Count('id')).order_by('status')
    return render(request, 'reports.html', {'stats': stats, 'wards': wards, 'patient_summary': summary,
        'transactions': StockTransaction.objects.select_related('medicine', 'performed_by')[:10]})


@roles_required('admin')
def feedback_list(request):
    return render(request, 'feedback_list.html', {'items': paginate(request,
        Feedback.objects.select_related('patient').all())})


@roles_required('patient')
def feedback_new(request):
    form = FeedbackForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        fb = form.save(commit=False)
        fb.patient = request.user
        fb.save()
        messages.success(request, 'Thank you! Your feedback was submitted.')
        return redirect('patient_dashboard')
    return render(request, 'form_page.html', {'form': form, 'page_title': 'Share feedback',
        'page_subtitle': 'Tell us about your hospital experience.', 'cancel_url': reverse('patient_dashboard')})
