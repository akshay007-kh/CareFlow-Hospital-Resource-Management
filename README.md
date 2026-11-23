# CareFlow — Hospital Resource Management System

A modern, responsive **Django + SQLite** hospital-resource management project with separate dashboards for **Administrator, Doctor, Nurse/Staff and Patient**.

> **For learning and project demonstrations.** This is not a certified production hospital record system. Do not use it to store real sensitive patient information or deploy publicly without a complete security/privacy review, independent tests, backups, monitoring, and regulatory assessment.

## Features

| Area | Functionality |
|---|---|
| Public | Responsive landing page, Login and Register |
| Accounts | Role selection during registration; patient immediate access, doctor/staff pending admin approval; admin provisioned securely |
| Separate dashboards | Admin `/dashboard/admin/`, Doctor `/dashboard/doctor/`, Staff `/dashboard/staff/`, Patient `/dashboard/patient/` |
| Administrator | Account approvals and editing, departments, patient records, wards and beds, equipment/inventory, medicine stock, equipment request approvals, reports, feedback |
| Doctor | Assigned patient details, treatment updates, bed availability, equipment requests, status tracking |
| Nurse/Staff | Patient registration/update, bed allocations/release, discharge, equipment issue/returns, stock-in/stock-out |
| Patient | Own patient profile and care details, assigned doctor and room, issued equipment, feedback |
| Business rules | Double bed allocation prevention; discharge releases bed; pending->approved->issued equipment workflow; resource returns; negative-stock protections; expired-medicine issue prevention |
| Interface | Responsive sidebar, cards, filters, search, pagination, notices, data lists, printable reports, mobile layouts |

## Windows setup in VS Code / PowerShell

Requires **Python 3.11+** and internet access for installing Django.

```powershell
cd Hospital_Resource_Management
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python manage.py makemigrations core
python manage.py migrate
python manage.py createsuperuser
python manage.py seed_demo
python manage.py runserver
```

Open **http://127.0.0.1:8000/** in your browser.

If PowerShell refuses venv activation, open a **Command Prompt** and use:

```bat
.venv\Scripts\activate.bat
```

Or skip activation and use `.venv\Scripts\python.exe` instead of `python` in each command.

### Optional fictional demo accounts

In a development environment only, generate a Doctor, Staff and Patient account automatically:

```powershell
python manage.py seed_demo --with-users
```

Passwords are generated randomly and printed when users are first created. Save them immediately. Run `python manage.py createsuperuser` separately for the Admin account. `seed_demo` refuses to run with `DJANGO_DEBUG=0`.

### Role-based registration and login

1. Landing page → **Register** → choose **Patient**, **Doctor** or **Nurse/Staff**.
2. **Patient**: a linked patient profile is created and login works immediately.
3. **Doctor / Nurse/Staff**: select a department; account waits for admin approval.
4. **Admin**: use `createsuperuser`, then log in using the regular Login page.
5. Admin goes to **Team & accounts** and selects **Approve** on pending Doctor/Staff users.
6. Everyone logs in at `/login/`; Django sends them to their **own dashboard URL**.

**Why Admin isn't an open registration choice:** allowing public users to register as an Administrator would let anyone take over patient records and hospital inventory. Admin accounts must be provisioned privately. The screen explicitly explains this.

### Suggested demo walkthrough

1. Log in as Admin → create departments/beds/equipment/medicine stock (or use `seed_demo`).
2. Create a Doctor and Nurse/Staff through registration → Admin approves both.
3. Add a patient in the Staff workspace → assign a Doctor.
4. Allocate a bed to the patient → bed automatically becomes occupied and patient admitted.
5. Doctor signs in → sees only their assigned patients, edits treatment, requests equipment for one patient.
6. Admin approves the request → Staff selects **Issue now**.
7. Staff marks equipment returned, discharges the patient → bed is automatically released.
8. Stock In/Out from the pharmacy updates quantity and writes a transaction record.
9. Patient signs in → views their own status and submits feedback; Admin sees feedback and reports.

## Automated tests

After installing Django and migrating:

```powershell
python manage.py check
python manage.py test core -v 2
```

Tests cover registration, admin role rejection, pending approvals, distinct role redirection, per-role permissions and visibility, bed allocation/release, discharge, equipment request/issue/return, stock protection and expired items.

## Main project structure

```text
Hospital_Resource_Management/
├── manage.py
├── requirements.txt
├── hospital_resource/
│   ├── settings.py
│   ├── urls.py
│   ├── asgi.py
│   └── wsgi.py
├── core/
│   ├── models.py
│   ├── forms.py
│   ├── views.py
│   ├── services.py
│   ├── urls.py
│   ├── admin.py
│   ├── tests.py
│   └── management/commands/seed_demo.py
├── templates/
│   ├── home.html, login.html, register.html
│   ├── dashboard_base.html
│   ├── admin_dashboard.html
│   ├── doctor_dashboard.html
│   ├── staff_dashboard.html
│   ├── patient_dashboard.html
│   └── (feature pages and shared partials)
└── static/
    ├── css/style.css
    └── js/main.js
```

The initial migration is intentionally generated **for the local installed Django version** with `python manage.py makemigrations core` prior to running `migrate`. Do not change `AUTH_USER_MODEL` after your first migration.

## Data model

- `User` — custom Django account with role, approval state and department.
- `Department` — staff and doctor organization.
- `Patient` — patient medical profile, optional linked registered account, assigned doctor and status.
- `Bed`, `BedAllocation` — room inventory and allocation history; partial unique constraints guard active assignments.
- `Equipment`, `EquipmentRequest`, `EquipmentAllocation` — unit inventory, doctor requests, approval and return history.
- `Medicine`, `StockTransaction` — auditable stock movements and expiry/low-stock indicators.
- `Feedback`, `ActivityLog` — patient feedback and activity history.

## Important notes

- Django built-in auth provides salted password hashing, permission-aware routes and CSRF form protection.
- User-supplied `role=admin` is invalid in public registration.
- Doctor/Staff pages require account approval. Only the Admin can approve new staff or doctors.
- Critical resource moves are wrapped in database transactions and database constraints.
- Resource history uses protected relationships; bed/equipment/medicine records are edited/retired instead of destructively deleted so audit history can be preserved.
- The UI uses Google Fonts when reachable; system fonts are provided as fallbacks, and all styling works without external CSS frameworks.
- SQLite is suitable for a class project/small local demo. Multi-user real hospitals should consider PostgreSQL and stronger infrastructure.

## Production considerations (not included)

Before any real patient usage: implement patient-data privacy policies and consent, comprehensive audit logs, password reset/email verification, HTTPS/HSTS, correct environment secrets and deployment settings, automated backups, clinical data standards, record retention, approved hosting, rate limiting, and clinical/governance review.