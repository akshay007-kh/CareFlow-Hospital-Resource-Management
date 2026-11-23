from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models
from django.db.models import Q
from django.utils import timezone


class Department(models.Model):
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class User(AbstractUser):
    class Role(models.TextChoices):
        ADMIN = 'admin', 'Administrator'
        DOCTOR = 'doctor', 'Doctor'
        STAFF = 'staff', 'Nurse / Staff'
        PATIENT = 'patient', 'Patient'

    role = models.CharField(max_length=12, choices=Role.choices, default=Role.PATIENT)
    phone = models.CharField(max_length=20, blank=True)
    department = models.ForeignKey(Department, on_delete=models.SET_NULL, null=True, blank=True)
    is_approved = models.BooleanField(default=False)

    def save(self, *args, **kwargs):
        if self.is_superuser:
            self.role = self.Role.ADMIN
            self.is_approved = True
        super().save(*args, **kwargs)

    @property
    def display_name(self):
        return self.get_full_name() or self.username

    def __str__(self):
        return f'{self.display_name} · {self.get_role_display()}'


class Patient(models.Model):
    class Gender(models.TextChoices):
        FEMALE = 'female', 'Female'
        MALE = 'male', 'Male'
        OTHER = 'other', 'Other'

    class Status(models.TextChoices):
        WAITING = 'waiting', 'Registered'
        ADMITTED = 'admitted', 'Admitted'
        DISCHARGED = 'discharged', 'Discharged'

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='patient_record')
    full_name = models.CharField(max_length=140)
    age = models.PositiveSmallIntegerField(null=True, blank=True, validators=[MaxValueValidator(125)])
    gender = models.CharField(max_length=10, choices=Gender.choices, blank=True)
    phone = models.CharField(max_length=20, blank=True)
    diagnosis = models.CharField(max_length=250, blank=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.WAITING)
    assigned_doctor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='assigned_patients', limit_choices_to={'role': User.Role.DOCTOR})
    admission_date = models.DateTimeField(null=True, blank=True)
    discharged_at = models.DateTimeField(null=True, blank=True)
    treatment_notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.full_name


class Bed(models.Model):
    class Ward(models.TextChoices):
        GENERAL = 'general', 'General Ward'
        ICU = 'icu', 'ICU'
        EMERGENCY = 'emergency', 'Emergency'
        PRIVATE = 'private', 'Private Room'

    number = models.CharField(max_length=30, unique=True)
    ward = models.CharField(max_length=12, choices=Ward.choices)
    floor = models.CharField(max_length=30, blank=True)
    is_active = models.BooleanField(default=True)
    under_maintenance = models.BooleanField(default=False)

    class Meta:
        ordering = ['ward', 'number']

    def __str__(self):
        return f'{self.number} · {self.get_ward_display()}'

    @property
    def occupied(self):
        return self.allocations.filter(released_at__isnull=True).exists()

    @property
    def availability(self):
        if not self.is_active:
            return 'Inactive'
        if self.under_maintenance:
            return 'Maintenance'
        return 'Occupied' if self.occupied else 'Available'


class BedAllocation(models.Model):
    bed = models.ForeignKey(Bed, on_delete=models.PROTECT, related_name='allocations')
    patient = models.ForeignKey(Patient, on_delete=models.PROTECT, related_name='bed_allocations')
    allocated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    allocated_at = models.DateTimeField(default=timezone.now)
    released_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-allocated_at']
        constraints = [
            models.UniqueConstraint(fields=['bed'], condition=Q(released_at__isnull=True), name='unique_active_patient_per_bed'),
            models.UniqueConstraint(fields=['patient'], condition=Q(released_at__isnull=True), name='unique_active_bed_per_patient'),
        ]

    def __str__(self):
        return f'{self.patient} → {self.bed.number}'


class Equipment(models.Model):
    class Condition(models.TextChoices):
        READY = 'ready', 'Operational'
        MAINTENANCE = 'maintenance', 'Under Maintenance'
        RETIRED = 'retired', 'Out of Service'

    name = models.CharField(max_length=120)
    code = models.CharField(max_length=40, unique=True)
    category = models.CharField(max_length=100)
    total_quantity = models.PositiveIntegerField(default=0)
    available_quantity = models.PositiveIntegerField(default=0)
    condition = models.CharField(max_length=16, choices=Condition.choices, default=Condition.READY)
    location = models.CharField(max_length=100, blank=True)

    class Meta:
        ordering = ['name', 'code']
        constraints = [models.CheckConstraint(condition=Q(available_quantity__lte=models.F('total_quantity')), name='equipment_available_lte_total')]

    def __str__(self):
        return f'{self.name} ({self.code})'


class EquipmentRequest(models.Model):
    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        APPROVED = 'approved', 'Approved'
        REJECTED = 'rejected', 'Rejected'
        FULFILLED = 'fulfilled', 'Issued'

    equipment = models.ForeignKey(Equipment, on_delete=models.PROTECT, related_name='requests')
    patient = models.ForeignKey(Patient, on_delete=models.PROTECT, related_name='equipment_requests')
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='equipment_requests')
    quantity = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    justification = models.TextField(blank=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']


class EquipmentAllocation(models.Model):
    request = models.OneToOneField(EquipmentRequest, on_delete=models.PROTECT, related_name='allocation')
    equipment = models.ForeignKey(Equipment, on_delete=models.PROTECT, related_name='allocations')
    patient = models.ForeignKey(Patient, on_delete=models.PROTECT, related_name='equipment_allocations')
    quantity = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    issued_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='+')
    allocated_at = models.DateTimeField(default=timezone.now)
    returned_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-allocated_at']


class Medicine(models.Model):
    name = models.CharField(max_length=120)
    sku = models.CharField(max_length=40, unique=True)
    unit = models.CharField(max_length=30, default='units')
    stock = models.PositiveIntegerField(default=0)
    minimum_stock = models.PositiveIntegerField(default=10)
    expiry_date = models.DateField(null=True, blank=True)
    location = models.CharField(max_length=100, blank=True)

    class Meta:
        ordering = ['name']

    @property
    def is_low(self):
        return self.stock <= self.minimum_stock

    @property
    def is_expired(self):
        return bool(self.expiry_date and self.expiry_date < timezone.localdate())

    def __str__(self):
        return self.name


class StockTransaction(models.Model):
    class Direction(models.TextChoices):
        IN = 'in', 'Stock In'
        OUT = 'out', 'Stock Out'

    medicine = models.ForeignKey(Medicine, on_delete=models.PROTECT, related_name='transactions')
    direction = models.CharField(max_length=3, choices=Direction.choices)
    quantity = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    note = models.CharField(max_length=200, blank=True)
    performed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']


class Feedback(models.Model):
    patient = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='feedback_entries')
    rating = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(5)])
    message = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']


class ActivityLog(models.Model):
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    action = models.CharField(max_length=180)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
