"""Reopen committed synthetic data in a fresh Django application process."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--database', type=Path, required=True)
parser.add_argument('--output', type=Path)
parser.add_argument('--read', action='store_true')
args = parser.parse_args()
root = Path(__file__).resolve().parents[1]
if args.database.resolve() == (root / 'db.sqlite3').resolve():
    parser.error('Use only the separate synthetic database.')
sys.path.insert(0, str(root))
os.environ['DJANGO_SETTINGS_MODULE'] = 'bbms.settings'
from django.conf import settings  # noqa: E402
settings.DATABASES['default']['NAME'] = str(args.database.resolve())
import django  # noqa: E402
django.setup()
from django.db import connections  # noqa: E402
from inventory.models import BloodUnit, DispatchManifest  # noqa: E402
from requisitions.models import DeliveryConfirmation, Requisition  # noqa: E402
from core.audit import verify_audit_log_integrity  # noqa: E402

snapshot = {
    'units': list(BloodUnit.objects.order_by('pk').values('bag_id', 'status', 'parent_unit_id')),
    'requests': list(Requisition.objects.order_by('pk').values('requisition_id', 'status', 'quantity')),
    'dispatches': list(DispatchManifest.objects.order_by('pk').values('manifest_id', 'requisition_id')),
    'receipts': list(DeliveryConfirmation.objects.order_by('pk').values('fulfilment_id', 'receiver_label', 'received_at')),
}
digest = hashlib.sha256(json.dumps(snapshot, sort_keys=True, default=str).encode()).hexdigest()
if args.read:
    print(digest)
else:
    connections.close_all()
    reopened = subprocess.check_output([
        sys.executable, str(Path(__file__).resolve()), '--database', str(args.database.resolve()), '--read',
    ], text=True).strip()
    valid, errors, count = verify_audit_log_integrity()
    result = {'method': 'Same committed database reopened by a fresh Django application process; no crash simulation',
              'matching_digest': digest == reopened, 'sha256': digest,
              'counts': {key: len(value) for key, value in snapshot.items()},
              'audit_chain_valid': valid, 'audit_errors': errors, 'audit_records': count}
    if args.output:
        args.output.write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result, indent=2))
    if not result['matching_digest'] or not valid:
        raise SystemExit(1)
