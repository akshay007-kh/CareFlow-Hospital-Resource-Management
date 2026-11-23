from datetime import timedelta
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from core.models import (User, Department, Patient, Bed, BedAllocation, Equipment, EquipmentRequest,
                         EquipmentAllocation, Medicine, StockTransaction)
from core.services import (ResourceError, allocate_bed, release_bed, discharge_patient,
                           review_equipment_request, return_equipment, move_stock, adjust_equipment)


class BaseHospitalTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.department = Department.objects.create(name='Emergency')
        cls.admin = User.objects.create_superuser('hospitaladmin', 'admin@example.invalid', 'AdminTestPass123!')
        cls.doctor = User.objects.create_user('doctor1', password='DoctorTestPass123!', role='doctor',
                                             department=cls.department, is_approved=True)
        cls.doctor2 = User.objects.create_user('doctor2', password='DoctorTestPass123!', role='doctor',
                                              department=cls.department, is_approved=True)
        cls.staff = User.objects.create_user('nurse1', password='StaffTestPass123!', role='staff',
                                            department=cls.department, is_approved=True)
        cls.patient_user = User.objects.create_user('patient1', password='PatientTestPass123!',
                                                    role='patient', is_approved=True)
        cls.patient = Patient.objects.create(user=cls.patient_user, full_name='Test Patient', assigned_doctor=cls.doctor)
        cls.other_patient = Patient.objects.create(full_name='Private Patient', assigned_doctor=cls.doctor2)
        cls.bed = Bed.objects.create(number='A-01', ward='general')
        cls.bed2 = Bed.objects.create(number='A-02', ward='general')
        cls.equipment = Equipment.objects.create(name='Wheelchair', code='WC01', category='Mobility',
                                                 total_quantity=3, available_quantity=3)
        cls.medicine = Medicine.objects.create(name='Paracetamol', sku='MD01', stock=20, minimum_stock=5)


class RegistrationTests(BaseHospitalTest):
    def test_patient_register_and_login_redirect(self):
        response = self.client.post(reverse('register'), {
            'username': 'newpatient', 'first_name': 'Mary', 'last_name': 'Joseph',
            'email': 'mary@example.invalid', 'phone': '9999999999', 'role': 'patient',
            'password1': 'GreatPassword456!', 'password2': 'GreatPassword456!',
        })
        self.assertRedirects(response, reverse('login'))
        user = User.objects.get(username='newpatient')
        self.assertTrue(user.is_approved)
        self.assertEqual(user.patient_record.full_name, 'Mary Joseph')
        self.client.force_login(user)
        self.assertRedirects(self.client.get(reverse('dashboard')), reverse('patient_dashboard'))

    def test_doctor_pending_until_approved(self):
        response = self.client.post(reverse('register'), {
            'username': 'newdoctor', 'first_name': 'John', 'last_name': 'George',
            'email': 'john@example.invalid', 'role': 'doctor', 'department': self.department.pk,
            'password1': 'GreatPassword456!', 'password2': 'GreatPassword456!',
        })
        self.assertRedirects(response, reverse('login'))
        user = User.objects.get(username='newdoctor')
        self.assertFalse(user.is_approved)
        denied = self.client.post(reverse('login'), {'username': 'newdoctor', 'password': 'GreatPassword456!'})
        self.assertContains(denied, 'waiting for administrator approval')
        self.client.force_login(self.admin)
        self.client.post(reverse('user_approval', args=[user.pk]))
        user.refresh_from_db()
        self.assertTrue(user.is_approved)
        self.client.logout()
        self.client.post(reverse('login'), {'username': 'newdoctor', 'password': 'GreatPassword456!'})
        self.assertRedirects(self.client.get(reverse('dashboard')), reverse('doctor_dashboard'))

    def test_register_cannot_choose_admin(self):
        self.client.post(reverse('register'), {
            'username': 'fakeadmin', 'first_name': 'Fake', 'last_name': 'Admin', 'email': 'fake@example.invalid',
            'role': 'admin', 'password1': 'GreatPassword456!', 'password2': 'GreatPassword456!',
        })
        self.assertFalse(User.objects.filter(username='fakeadmin').exists())

    def test_role_redirects(self):
        for user, dest in [(self.admin, 'admin_dashboard'), (self.staff, 'staff_dashboard'),
                           (self.doctor, 'doctor_dashboard'), (self.patient_user, 'patient_dashboard')]:
            self.client.force_login(user)
            self.assertRedirects(self.client.get(reverse('dashboard')), reverse(dest))


class SecurityTests(BaseHospitalTest):
    def test_patient_cannot_access_admin_or_staff_pages(self):
        self.client.force_login(self.patient_user)
        for page in ('users', 'reports', 'medicines', 'patient_new', 'equipment_allocations'):
            self.assertEqual(self.client.get(reverse(page)).status_code, 403)

    def test_doctor_only_sees_assigned_patient(self):
        self.client.force_login(self.doctor)
        self.assertEqual(self.client.get(reverse('patient_detail', args=[self.patient.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse('patient_detail', args=[self.other_patient.pk])).status_code, 403)
        patients = self.client.get(reverse('patients'))
        self.assertContains(patients, 'Test Patient')
        self.assertNotContains(patients, 'Private Patient')
        beds = self.client.get(reverse('beds'))
        self.assertNotContains(beds, 'Private Patient')

    def test_staff_cannot_approve_equipment_request(self):
        req = EquipmentRequest.objects.create(patient=self.patient, equipment=self.equipment,
                                              requested_by=self.doctor, quantity=1)
        self.client.force_login(self.staff)
        response = self.client.post(reverse('equipment_request_action', args=[req.pk]), {'action': 'approve'})
        self.assertEqual(response.status_code, 403)
        req.refresh_from_db()
        self.assertEqual(req.status, 'pending')

    def test_http_get_cannot_mutate_approval(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse('user_approval', args=[self.doctor.pk])).status_code, 405)


class ResourceWorkflowTests(BaseHospitalTest):
    def test_no_double_book_bed_or_patient(self):
        allocate_bed(self.patient.pk, self.bed.pk, self.staff)
        self.assertEqual(self.patient.bed_allocations.filter(released_at__isnull=True).count(), 1)
        with self.assertRaises(ResourceError):
            allocate_bed(self.other_patient.pk, self.bed.pk, self.staff)
        with self.assertRaises(ResourceError):
            allocate_bed(self.patient.pk, self.bed2.pk, self.staff)
        self.bed.refresh_from_db()
        self.assertTrue(self.bed.occupied)

    def test_release_then_reassign(self):
        allocation = allocate_bed(self.patient.pk, self.bed.pk, self.staff)
        release_bed(allocation.pk, self.staff)
        self.assertFalse(Bed.objects.get(pk=self.bed.pk).occupied)
        allocate_bed(self.other_patient.pk, self.bed.pk, self.staff)
        self.assertEqual(BedAllocation.objects.filter(bed=self.bed, released_at__isnull=True).count(), 1)

    def test_discharge_releases_bed(self):
        allocate_bed(self.patient.pk, self.bed.pk, self.staff)
        discharge_patient(self.patient.pk, self.staff)
        self.patient.refresh_from_db()
        self.assertEqual(self.patient.status, 'discharged')
        self.assertFalse(self.bed.occupied)

    def test_equipment_request_approval_issue_and_return(self):
        req = EquipmentRequest.objects.create(patient=self.patient, equipment=self.equipment,
                                              requested_by=self.doctor, quantity=2)
        review_equipment_request(req.pk, self.admin, 'approve')
        review_equipment_request(req.pk, self.staff, 'fulfill')
        req.refresh_from_db()
        self.equipment.refresh_from_db()
        self.assertEqual(req.status, 'fulfilled')
        self.assertEqual(self.equipment.available_quantity, 1)
        allocation = EquipmentAllocation.objects.get(request=req)
        return_equipment(allocation.pk, self.staff)
        self.equipment.refresh_from_db()
        self.assertEqual(self.equipment.available_quantity, 3)
        with self.assertRaises(ResourceError):
            return_equipment(allocation.pk, self.staff)

    def test_equipment_inventory_adjustment_protects_issued_units(self):
        req = EquipmentRequest.objects.create(patient=self.patient, equipment=self.equipment,
                                              requested_by=self.doctor, quantity=2)
        review_equipment_request(req.pk, self.admin, 'approve')
        review_equipment_request(req.pk, self.staff, 'fulfill')
        with self.assertRaises(ResourceError):
            adjust_equipment(self.equipment.pk, -2, self.admin)

    def test_medicine_stock_protects_negative_and_expired_issues(self):
        move_stock(self.medicine.pk, 'out', 3, self.staff, 'Ward supply')
        self.medicine.refresh_from_db()
        self.assertEqual(self.medicine.stock, 17)
        self.assertEqual(StockTransaction.objects.count(), 1)
        with self.assertRaises(ResourceError):
            move_stock(self.medicine.pk, 'out', 18, self.staff)
        self.medicine.expiry_date = timezone.localdate() - timedelta(days=1)
        self.medicine.save(update_fields=['expiry_date'])
        with self.assertRaises(ResourceError):
            move_stock(self.medicine.pk, 'out', 1, self.staff)

    def test_cannot_discharge_with_outstanding_equipment(self):
        allocate_bed(self.patient.pk, self.bed.pk, self.staff)
        req = EquipmentRequest.objects.create(patient=self.patient, equipment=self.equipment,
                                              requested_by=self.doctor, quantity=1)
        review_equipment_request(req.pk, self.admin, 'approve')
        review_equipment_request(req.pk, self.staff, 'fulfill')
        with self.assertRaises(ResourceError):
            discharge_patient(self.patient.pk, self.staff)
        self.patient.refresh_from_db()
        self.assertEqual(self.patient.status, 'admitted')
