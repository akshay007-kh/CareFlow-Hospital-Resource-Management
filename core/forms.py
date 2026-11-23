from django import forms
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.db.models import Q
from .models import (User, Department, Patient, Bed, BedAllocation, Equipment,
                     EquipmentRequest, Medicine, StockTransaction, Feedback)


class StyledForm:
    def apply_style(self):
        for field in self.fields.values():
            widget = field.widget
            css = 'check-input' if isinstance(widget, forms.CheckboxInput) else 'form-control'
            widget.attrs['class'] = f"{widget.attrs.get('class', '')} {css}".strip()
            if isinstance(widget, forms.Textarea):
                widget.attrs.setdefault('rows', 3)


class StyledModelForm(StyledForm, forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.apply_style()


class StyledBasicForm(StyledForm, forms.Form):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.apply_style()


class LoginForm(StyledForm, AuthenticationForm):
    username = forms.CharField(label='Username')
    password = forms.CharField(widget=forms.PasswordInput)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.apply_style()

    def confirm_login_allowed(self, user):
        super().confirm_login_allowed(user)
        if user.role in (User.Role.DOCTOR, User.Role.STAFF) and not user.is_approved:
            raise forms.ValidationError('Your account is waiting for administrator approval.', code='pending')


class RegistrationForm(StyledForm, UserCreationForm):
    role = forms.ChoiceField(choices=[('', 'Choose your account type'),
                                      (User.Role.PATIENT, 'Patient'),
                                      (User.Role.DOCTOR, 'Doctor'),
                                      (User.Role.STAFF, 'Nurse / Staff')], label='User type')
    first_name = forms.CharField(max_length=100, label='First name')
    last_name = forms.CharField(max_length=100, label='Last name')
    email = forms.EmailField(required=True)
    phone = forms.CharField(max_length=20, required=False)
    department = forms.ModelChoiceField(queryset=Department.objects.none(), required=False, empty_label='Select department (for staff)')

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ('username', 'first_name', 'last_name', 'email', 'phone', 'role', 'department', 'password1', 'password2')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['department'].queryset = Department.objects.filter(is_active=True)
        self.apply_style()
        self.fields['username'].help_text = 'Letters, numbers and @/./+/-/_ only.'
        self.fields['password1'].help_text = 'Use a strong password (at least 8 characters).'
        self.fields['password2'].help_text = ''

    def clean_email(self):
        email = self.cleaned_data['email'].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError('An account with this email already exists.')
        return email

    def clean(self):
        cleaned = super().clean()
        if cleaned.get('role') in (User.Role.DOCTOR, User.Role.STAFF) and not cleaned.get('department'):
            self.add_error('department', 'Select your hospital department.')
        return cleaned

    def save(self, commit=True):
        user = super().save(commit=False)
        user.role = self.cleaned_data['role']
        user.is_approved = user.role == User.Role.PATIENT
        if commit:
            user.save()
            if user.role == User.Role.PATIENT:
                Patient.objects.create(user=user, full_name=user.display_name, phone=user.phone)
        return user


class DepartmentForm(StyledModelForm):
    class Meta:
        model = Department
        fields = ['name', 'description', 'is_active']


class UserEditForm(StyledModelForm):
    class Meta:
        model = User
        fields = ['first_name', 'last_name', 'email', 'phone', 'department', 'is_active']

    def clean_email(self):
        email = self.cleaned_data['email'].strip().lower()
        if User.objects.filter(email__iexact=email).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError('An account with this email already exists.')
        return email


class PatientForm(StyledModelForm):
    class Meta:
        model = Patient
        fields = ['full_name', 'age', 'gender', 'phone', 'diagnosis', 'assigned_doctor', 'treatment_notes']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['assigned_doctor'].queryset = User.objects.filter(role=User.Role.DOCTOR, is_approved=True, is_active=True)


class PatientSelfForm(StyledModelForm):
    class Meta:
        model = Patient
        fields = ['age', 'gender', 'phone']


class TreatmentForm(StyledModelForm):
    class Meta:
        model = Patient
        fields = ['diagnosis', 'treatment_notes']


class BedForm(StyledModelForm):
    class Meta:
        model = Bed
        fields = ['number', 'ward', 'floor', 'is_active', 'under_maintenance']

    def clean(self):
        cleaned = super().clean()
        if self.instance.pk and (cleaned.get('under_maintenance') or not cleaned.get('is_active')):
            if BedAllocation.objects.filter(bed=self.instance, released_at__isnull=True).exists():
                raise forms.ValidationError('Release the current patient before deactivating this bed or setting maintenance.')
        return cleaned


class BedAllocationForm(StyledBasicForm):
    patient = forms.ModelChoiceField(queryset=Patient.objects.none())
    bed = forms.ModelChoiceField(queryset=Bed.objects.none())

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        allocated_patients = BedAllocation.objects.filter(released_at__isnull=True).values_list('patient_id', flat=True)
        occupied_beds = BedAllocation.objects.filter(released_at__isnull=True).values_list('bed_id', flat=True)
        self.fields['patient'].queryset = Patient.objects.exclude(status=Patient.Status.DISCHARGED).exclude(pk__in=allocated_patients)
        self.fields['bed'].queryset = Bed.objects.filter(is_active=True, under_maintenance=False).exclude(pk__in=occupied_beds)


class EquipmentCreateForm(StyledModelForm):
    class Meta:
        model = Equipment
        fields = ['name', 'code', 'category', 'total_quantity', 'condition', 'location']

    def save(self, commit=True):
        equipment = super().save(commit=False)
        equipment.available_quantity = equipment.total_quantity
        if commit:
            equipment.save()
        return equipment


class EquipmentEditForm(StyledModelForm):
    class Meta:
        model = Equipment
        fields = ['name', 'code', 'category', 'condition', 'location']


class EquipmentAdjustmentForm(StyledBasicForm):
    delta = forms.IntegerField(label='Change quantity (+/-)', help_text='Positive adds units; negative removes available units.')


class EquipmentRequestForm(StyledModelForm):
    class Meta:
        model = EquipmentRequest
        fields = ['patient', 'equipment', 'quantity', 'justification']

    def __init__(self, *args, **kwargs):
        self.doctor = kwargs.pop('doctor')
        super().__init__(*args, **kwargs)
        self.fields['patient'].queryset = Patient.objects.filter(assigned_doctor=self.doctor).exclude(status=Patient.Status.DISCHARGED)
        self.fields['equipment'].queryset = Equipment.objects.filter(condition=Equipment.Condition.READY)

    def clean_quantity(self):
        quantity = self.cleaned_data['quantity']
        if quantity < 1:
            raise forms.ValidationError('Quantity must be positive.')
        return quantity


class MedicineCreateForm(StyledModelForm):
    class Meta:
        model = Medicine
        fields = ['name', 'sku', 'unit', 'stock', 'minimum_stock', 'expiry_date', 'location']
        widgets = {'expiry_date': forms.DateInput(attrs={'type': 'date'})}


class MedicineEditForm(StyledModelForm):
    class Meta:
        model = Medicine
        fields = ['name', 'sku', 'unit', 'minimum_stock', 'expiry_date', 'location']
        widgets = {'expiry_date': forms.DateInput(attrs={'type': 'date'})}


class StockMovementForm(StyledBasicForm):
    direction = forms.ChoiceField(choices=StockTransaction.Direction.choices)
    quantity = forms.IntegerField(min_value=1)
    note = forms.CharField(max_length=200, required=False)


class FeedbackForm(StyledModelForm):
    class Meta:
        model = Feedback
        fields = ['rating', 'message']
        widgets = {'rating': forms.Select(choices=[('', 'Choose rating')] + [(i, f'{i} out of 5') for i in range(5, 0, -1)])}
