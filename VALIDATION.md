# Validation record

## Checks completed in this build environment

- Python source syntax: **PASS** (`python -m compileall`)
- URL route-name/static-template references: **PASS** (44 URL names matched, zero missing)
- Django template `if` / `for` / `block` nesting: **PASS** (static balance check; 26 templates)
- Referenced Django view functions: **PASS** (no undefined view names)

## Checks NOT run in this build environment

The build environment does not have Django installed, and package installation failed because internet/name resolution was unavailable. Consequently **Django migration checks, Django automated tests, and browser/UI acceptance tests have not been executed** here. Their success is **not guaranteed**.

Run these commands on your Windows machine after installing dependencies:

```powershell
python manage.py makemigrations core
python manage.py migrate
python manage.py check
python manage.py test core -v 2
python manage.py runserver
```

## Manual acceptance checklist

- [ ] Landing page looks correct on desktop and mobile; login and register buttons work
- [ ] Patient self-registers and enters Patient dashboard
- [ ] Doctor/Staff require admin approval and cannot access the app beforehand
- [ ] Admin account created through `createsuperuser` accesses Administrator dashboard
- [ ] Doctor sees assigned patients only and can submit equipment requests
- [ ] Staff can create patient records, allocate/release beds and process pharmacy stock
- [ ] Admin can approve Doctor/Staff registrations and equipment requests
- [ ] Staff fulfills approved equipment requests; returning equipment restores stock
- [ ] Duplicate bed allocation and medicine stock underflow are blocked
- [ ] Discharge releases active beds and blocks if equipment hasn't been returned
- [ ] Patient can view only their own record and submit feedback
- [ ] Reports show live records and print correctly
