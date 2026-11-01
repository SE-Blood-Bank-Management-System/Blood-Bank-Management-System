# Sprint 2 setup and user guide

Use Python 3.10+ with the Django 5.2-compatible dependency range in the repository.
Create/activate a virtual environment, then run:

```text
python -m pip install -r requirements-dev.txt
python manage.py migrate
python manage.py check
python manage.py makemigrations --check --dry-run
flake8 .
coverage run manage.py test
coverage report --fail-under=60
```

For normal local HTTP development set `BBMS_SECURE_COOKIES=0` in the shell before
`python manage.py runserver 127.0.0.1:8000`. Use `$env:BBMS_SECURE_COOKIES='0'` in
PowerShell or `export BBMS_SECURE_COOKIES=0` on POSIX. Environment values are read
directly by settings; copying an `.env` file alone does not load it automatically.

For the isolated team-name demo, keep a separate synthetic SQLite file:

```text
python demo/run_sprint2.py --database ../bbms-sprint2-demo.sqlite3 --port 8772
```

This runner binds only to loopback, disables Secure cookies only for its local
HTTP process, uses an in-memory mail backend and never opens the normal
`db.sqlite3`. It refuses that database path. A fresh empty database is seeded;
existing data is preserved on restart. The demo-only password is
`SyntheticDemo!49` unless `BBMS_DEMO_PASSWORD` was set before the first seed.

| Demo account | Role / use |
| --- | --- |
| abhinav | Approved hospital: create a B+ RBC quantity-2 STAT request; confirm receipt after dispatch. |
| uttam | Staff: review request, cross-match Bag ID, inspect FEFO suggestions, allocate and dispatch. |
| navaneeth | Synthetic donor associated with collected bags; donor self-service remains available. |
| akshay | Administrator: component separation, reports/CSV and central read-only audit. |

1. Hospital Portal → New requisition. Enter group/component/quantity/required date
   and optional STAT; submit for staff approval.
2. Staff sees the persistent live STAT alert and Requisition Queue. Approve or
   reject with a reason, then cross-match a candidate Bag ID. Unsafe/expired stock
   is excluded; a policy-incompatible allocation requires a justified override.
3. Allocate Units (FEFO) → choose actual bags → Confirm Allocation. Available
   counts fall on reservation. Dispatch Reserved Units → select bags → generate
   a manifest; partial/full fulfilment follows dispatched quantities.
4. Hospital opens its own request, inspects manifest and Bag IDs, and confirms
   physically received bags. Each becomes Delivered with receiver/time history.
5. Staff/admin can separate safe whole blood from its unit detail. Parent status
   becomes Separated; child Bag IDs retain source collection/expiry and serology.
6. Admin Reports supports stock, donation activity and requisition fulfilment CSV
   exports. Audit Log supports read-only filtering and chain verification.

`python manage.py expire_units` performs the expiry sweep. Schedule it in the
deployment; there is no background scheduler merely because the command exists.
Use `python manage.py verify_audit_integrity` for chain verification. See each
feature's linked documentation for detailed rules and retained limitations.

Production requires a strong secret, explicit hosts/origins, HTTPS termination,
secure cookies, trusted-proxy boundaries, SMTP configuration, migrations/static
collection, backups and a supported application server. See
[secure deployment guidance](../password-reset-and-security.md). Run
`check --deploy` with the actual deployment environment. A passing configuration
check does not prove deployed TLS, uptime or performance.

The final [acceptance record](acceptance.md) lists required owner actions and
remaining evidence. Do not treat the local seed or video as production deployment.
