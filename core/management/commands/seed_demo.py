"""Seed fictional inventory and optional LOCAL-ONLY demo users."""
import secrets
from datetime import timedelta
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from core.models import Department, User, Patient, Bed, Equipment, Medicine


class Command(BaseCommand):
    help = 'Create fictional department, beds, equipment and medicine demo records. --with-users also creates local test users.'

    def add_arguments(self, parser):
        parser.add_argument('--with-users', action='store_true', help='Create LOCAL development demo accounts with generated passwords')

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError('Demo seed is disabled when DJANGO_DEBUG=0.')
        departments = {}
        for name, desc in [('General Medicine', 'General consultation and patient services'),
                           ('Cardiology', 'Heart and circulation'),
                           ('Emergency', 'Critical and urgent services'),
                           ('Intensive Care', 'Critical patient monitoring'),
                           ('Pharmacy', 'Medicines and inventory management')]:
            departments[name], _ = Department.objects.get_or_create(name=name, defaults={'description': desc})
        for ward, prefix, count in [('general', 'GN', 9), ('icu', 'ICU', 5), ('emergency', 'ER', 4), ('private', 'PR', 3)]:
            for i in range(1, count + 1):
                Bed.objects.get_or_create(number=f'{prefix}-{i:02d}', defaults={'ward': ward, 'floor': 'Ground' if ward == 'emergency' else 'First'})
        for name, code, category, count, location in [
            ('Portable Ventilator', 'EQ-VEN-01', 'Respiratory', 8, 'ICU'),
            ('Wheelchair', 'EQ-WHL-01', 'Mobility', 17, 'Central Stores'),
            ('Patient Monitor', 'EQ-MON-01', 'Monitoring', 12, 'ICU'),
            ('Infusion Pump', 'EQ-INF-01', 'Infusion', 14, 'Ward A'),
            ('Oxygen Cylinder', 'EQ-OXY-01', 'Respiratory', 22, 'Central Stores'),
            ('ECG Machine', 'EQ-ECG-01', 'Diagnostics', 4, 'Cardiology'),
        ]:
            Equipment.objects.get_or_create(code=code, defaults={'name': name, 'category': category,
                'total_quantity': count, 'available_quantity': count, 'location': location})
        today = timezone.localdate()
        for name, sku, stock, minimum in [('Paracetamol 500mg', 'MED-PAR-500', 220, 35),
                                           ('Saline 500ml', 'MED-SAL-500', 45, 20),
                                           ('Amoxicillin 250mg', 'MED-AMX-250', 15, 20),
                                           ('Bandage Roll', 'MED-BND-001', 130, 30),
                                           ('Surgical Gloves', 'MED-GLV-001', 70, 40),
                                           ('Metformin 500mg', 'MED-MET-500', 24, 30)]:
            Medicine.objects.get_or_create(sku=sku, defaults={'name': name, 'stock': stock,
                'minimum_stock': minimum, 'expiry_date': today + timedelta(days=180), 'location': 'Main pharmacy'})
        self.stdout.write(self.style.SUCCESS('Demo departments, beds, equipment and medicines are ready.'))
        if options['with_users']:
            accounts = [('cf_doctor', 'doctor', departments['General Medicine'], 'Asha', 'Menon'),
                        ('cf_nurse', 'staff', departments['Emergency'], 'Riya', 'Thomas'),
                        ('cf_patient', 'patient', None, 'Arun', 'Nair')]
            for username, role, dept, first, last in accounts:
                if User.objects.filter(username=username).exists():
                    self.stdout.write(f'{username}: already exists; credentials unchanged')
                    continue
                password = secrets.token_urlsafe(12)
                account = User.objects.create_user(username=username, password=password, role=role,
                    department=dept, first_name=first, last_name=last,
                    email=f'{username}@example.invalid', is_approved=True)
                if role == 'patient':
                    Patient.objects.get_or_create(user=account, defaults={'full_name': account.display_name, 'age': 29})
                self.stdout.write(f'{username} ({role}) => generated password: {password}')
            self.stdout.write(self.style.WARNING('Copy demo passwords now. They are printed only at creation. Never use these accounts with real patient data.'))
