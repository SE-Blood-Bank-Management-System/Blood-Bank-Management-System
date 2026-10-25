# Issue #14: Quarantine list and status-change history

## Requirements

Implements Issue #14, SRS BBMS-F-028 to F-030 and TC-QNT-01 using the existing
BloodUnit statuses, custom User model, RBAC and serology workflow.

The staff quarantine queue shows only currently Quarantined units with Bag ID,
blood groups when known, donor, component, collection time and elapsed quarantine
duration. It is paginated at 25 units per page, with an accurate total count.
Status history remains accessible from the unit detail page after the unit leaves
quarantine. Both the queue and history are staff/admin-only and non-cacheable.

## Status recording

StatusChange stores the blood-unit FK, previous/new statuses, responsible user,
username snapshot, timestamp and reason. Creation records an initial state with
an empty previous status. Every subsequent persisted change through save() is
recorded; unchanged saves and unrelated partial updates create no false events.

BloodUnit.save(actor=staff_user, status_reason='...') locks the stored unit row
and writes the new state and history in one transaction. It compares against the
stored state, so a stale instance cannot invent the previous status or overwrite
existing text history. Collection forms, record_collection, serology and Django
admin pass the actual staff user. Internal operations without an actor are
identified explicitly as System rather than attributed to an invented user.

Serology panels and individual results run atomically with their resulting
status/history change. An invalid panel or failed history insert rolls back the
results and unit state. Existing serology validation is retained.

QuerySet.update(status=...) and bulk_update(..., ['status']) are rejected; callers
must use the audited save path. Bulk creation uses audited per-unit inserts and
rejects conflict-skipping/upsert modes, preserving creation history.

## Retention and migration

Run `python manage.py migrate` to apply inventory migration 0004.

Existing text audit notes are preserved and displayed alongside new structured
history. No historical staff identities or event times are fabricated. Existing
quarantined rows get collection_date as their starting-time fallback because
previous releases did not store an independent quarantine-entry timestamp.

New collections start their quarantine clock at collection_date. A later return
to quarantine sets quarantined_at to the actual transition time. Leaving
quarantine clears the current clock; the historical entry remains in the log.
Future-dated source records never display a negative elapsed duration.

Status entries cannot be edited, overwritten or deleted through supported model,
queryset or admin interfaces. A stored unit with history is protected from
deletion. If a staff account is renamed/deleted, its original username snapshot
is retained; account deletion may unlink the user FK without losing identity.
These are application/ORM protections, not a cryptographic audit chain.

## Views and APIs

- `/inventory/quarantine/`: current queue; JSON is also available through Accept.
- `/inventory/blood-units/<bag_id>/status-history/`: read-only per-unit history.
- `/api/quarantine/`: paginated queue JSON including entry time and duration.
- `/api/blood-units/<bag_id>/status-history/`: structured entries and legacy notes.

Anonymous HTML requests redirect to login; anonymous API requests return 401.
Donors and hospitals receive 403. Unsafe methods receive 405. No arbitrary status
mutation endpoint is introduced; staff keep using the established collection,
serology and authorized admin workflows.

Public availability and the staff dashboard share BloodUnit.objects.available(),
which excludes Quarantined, Discarded and expired units. A lack of usable stock
shows actual zero counts; the previous sample-stock fallback is removed.

## Verification

The change adds 27 tests for status/actor/timestamp accuracy, initial records,
no-op and partial saves, stale objects, re-entry timing, transaction rollback,
immutability, actor retention, bulk-write guards, migration preservation,
permissions, JSON/HTML views, pagination, unknown groups and zero/unsafe stock.

Recorded verification: the 14-test baseline, all 27 new feature tests and the
full 202-test suite passed with the normal project password settings. Flake8,
Django system checks, migration-drift checks and whitespace checks passed.

```bash
python manage.py test inventory.test_status_transitions inventory.test_status_integrity inventory.test_status_migration inventory.test_quarantine_views
python manage.py test --parallel 4
python -m flake8 .
python manage.py check
python manage.py makemigrations --check --dry-run
git diff --check
```

Manual review: record a collection; inspect its initial history; record a passing
or failed serology panel; verify the transition actor/time and queue membership.
Confirm history is still readable after release/disposal. Sign in as a donor or
hospital user and confirm staff-only pages cannot be accessed. Review history
before deleting units: records with audit history are deliberately protected.
