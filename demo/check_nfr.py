"""Loopback HTTP timings with 50 distinct real sessions and a synthetic database.

Use against a separately started demo/run_sprint2.py instance on port 8773.
This is local development-server evidence, not a production load certification.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import date
import json
import os
from pathlib import Path
import statistics
import sys
import threading
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--database', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
root = Path(__file__).resolve().parents[1]
if args.database.resolve() == (root / 'db.sqlite3').resolve():
    parser.error('Use a separate synthetic database, not db.sqlite3.')
sys.path.insert(0, str(root))
os.environ['DJANGO_SETTINGS_MODULE'] = 'bbms.settings'
from django.conf import settings  # noqa: E402
settings.DATABASES['default']['NAME'] = str(args.database.resolve())
settings.ALLOWED_HOSTS = ['127.0.0.1', 'localhost', 'testserver']
from django import setup  # noqa: E402
setup()
from django.db import connections  # noqa: E402
from django.middleware.csrf import _get_new_csrf_string  # noqa: E402
from django.test import Client  # noqa: E402
from accounts.models import User  # noqa: E402
from appointments.models import AppointmentSlot  # noqa: E402
from donors.models import MedicalEligibilityResponse  # noqa: E402

base = 'http://127.0.0.1:8773'
run_id = str(int(time.time()))
sessions = []
for index in range(50):
    user, _ = User.objects.get_or_create(username=f'nfr_{run_id}_{index}', defaults={
        'role': 'DONOR', 'date_of_birth': date(1999, 1, 1), 'email': f'nfr{run_id}_{index}@example.test',
    })
    MedicalEligibilityResponse.objects.get_or_create(donor=user, status='Eligible')
    client = Client()
    client.force_login(user)
    csrf = _get_new_csrf_string()
    sessions.append((f'sessionid={client.cookies["sessionid"].value}; csrftoken={csrf}', csrf))
slot = AppointmentSlot.objects.get(location__name='Uttam Blood Bank')
slot_id = slot.pk
connections.close_all()


def request(index, path, barrier=None, data=None):
    cookie, csrf = sessions[index]
    headers = {'Cookie': cookie, 'X-CSRFToken': csrf, 'Accept': 'application/json'}
    if data is not None:
        headers['Content-Type'] = 'application/json'
    req = Request(base + path, headers=headers, data=json.dumps(data).encode() if data is not None else None)
    if barrier:
        barrier.wait(timeout=30)
    start = time.perf_counter()
    try:
        with urlopen(req, timeout=30) as response:
            content = response.read()
            status = response.status
    except HTTPError as error:
        content, status = error.read(), error.code
    except Exception as error:
        content, status = str(error).encode(), 0
    return {'seconds': round(time.perf_counter() - start, 6), 'status': status,
            'bytes': len(content), 'detail': content[:200].decode(errors='replace') if status not in (200, 201) else ''}


def measure(path, limit, concurrent=True, data=None, count=50):
    barrier = threading.Barrier(count) if concurrent else None
    if concurrent:
        with ThreadPoolExecutor(max_workers=count) as executor:
            results = list(executor.map(lambda i: request(i, path, barrier, data), range(count)))
    else:
        results = [request(i, path, data=data) for i in range(count)]
    times = sorted(result['seconds'] for result in results)
    return {'path': path, 'concurrent_sessions': count if concurrent else 1, 'requests': count,
            'median_seconds': statistics.median(times), 'p95_seconds': times[max(0, int(.95 * len(times)) - 1)],
            'max_seconds': max(times), 'limit_seconds': limit,
            'passed': all(r['status'] in (200, 201) and r['seconds'] <= limit for r in results),
            'results': results}


output = {
    'environment': 'Windows / Python / Django runserver / SQLite / loopback; synthetic seed only',
    'started_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
    'search_50_sessions': measure('/availability/', 2),
    'authenticated_50_sessions': measure('/api/appointments/', 2),
    'booking_10_samples': measure('/api/appointments/', 3, concurrent=False, count=10, data={'slot_id': slot_id}),
}
args.output.write_text(json.dumps(output, indent=2), encoding='utf-8')
print(json.dumps({key: {k: v for k, v in value.items() if k != 'results'}
                  for key, value in output.items() if isinstance(value, dict)}, indent=2))
