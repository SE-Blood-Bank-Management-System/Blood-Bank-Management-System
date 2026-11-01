"""Isolated, loopback-only Sprint 2 demo. Never opens the normal project database."""
import argparse
from datetime import date, time, timedelta
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--database', type=Path, required=True)
parser.add_argument('--port', type=int, default=8772)
parser.add_argument('--seed-only', action='store_true')
args = parser.parse_args()
database = args.database.resolve()
if database == (ROOT / 'db.sqlite3').resolve():
    parser.error('Use a separate synthetic database, not db.sqlite3.')
os.environ['DJANGO_SETTINGS_MODULE'] = 'bbms.settings'
from django.conf import settings  # noqa: E402
settings.DATABASES['default']['NAME'] = str(database)
settings.ALLOWED_HOSTS = ['127.0.0.1', 'localhost']
settings.SESSION_COOKIE_SECURE = False
settings.CSRF_COOKIE_SECURE = False
settings.EMAIL_BACKEND = 'django.core.mail.backends.locmem.EmailBackend'
import django  # noqa: E402
django.setup()
from django.core.management import call_command  # noqa: E402
from django.utils import timezone  # noqa: E402
from accounts.models import User  # noqa: E402
from appointments.models import AppointmentSlot, BloodBankLocation  # noqa: E402
from inventory.models import BloodUnit, ComponentType, REQUIRED_SEROLOGY_TESTS  # noqa: E402

call_command('migrate', interactive=False, verbosity=0)
if not User.objects.exists():
    password = os.environ.get('BBMS_DEMO_PASSWORD', 'SyntheticDemo!49')
    users = {}
    for name, role in [('abhinav', 'HOSPITAL'), ('uttam', 'STAFF'), ('navaneeth', 'DONOR'), ('akshay', 'ADMIN')]:
        users[name] = User.objects.create_user(
            name, email=f'{name}@example.test', password=password, role=role,
            first_name=name.capitalize(), is_approved=True,
            hospital_name='Abhinav Hospital' if role == 'HOSPITAL' else '',
            date_of_birth=date(1999, 1, 1), blood_group='B+', is_staff=role in ('STAFF', 'ADMIN'),
        )
    location = BloodBankLocation.objects.create(name='Uttam Blood Bank', city='Bengaluru', is_active=True)
    AppointmentSlot.objects.create(location=location, date=timezone.localdate() + timedelta(days=2),
                                   start_time=time(10), end_time=time(11), max_capacity=60)
    for bag, component, age, state in [
        ('BAG-ABHINAV-01', ComponentType.RBC, 4, 'Available'),
        ('BAG-NAVANEETH-02', ComponentType.RBC, 1, 'Available'),
        ('BAG-AKSHAY-WHOLE', ComponentType.WHOLE_BLOOD, 1, 'Available'),
        ('BAG-UTTAM-UNSAFE', ComponentType.RBC, 1, 'Quarantined'),
        ('BAG-EXPIRED-DEMO', ComponentType.RBC, 43, 'Expired'),
    ]:
        unit = BloodUnit.objects.create(
            bag_id=bag, donor=users['navaneeth'], collected_by=users['uttam'], blood_group='B+',
            component_type=component, collection_date=timezone.now() - timedelta(days=age),
            status='Quarantined', location=location.name,
        )
        if state != 'Quarantined':
            unit.record_serology_panel({kind: 'Pass' for kind in REQUIRED_SEROLOGY_TESTS}, staff_user=users['uttam'])
        if state == 'Expired':
            unit.status = state
            unit.save(actor=users['uttam'], status_reason='Synthetic overdue inventory.')
    print('Synthetic accounts: abhinav (hospital), uttam (staff), navaneeth (donor), akshay (admin).')
print(f'DEMO READY: http://127.0.0.1:{args.port}/', flush=True)
if not args.seed_only:
    call_command('runserver', f'127.0.0.1:{args.port}', use_reloader=False)

