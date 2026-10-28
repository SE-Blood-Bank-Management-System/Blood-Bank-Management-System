# Hospital requisitions and STAT review (Issue #30)

Implements BBMS-F-042–F-048 using the existing hospital account, approval and
session controls. Run `python manage.py migrate` before starting the application.
The new tables do not replace existing donor, inventory or account records.

## Hospital and staff workflow

Approved, active hospital users open **Hospital Portal**, submit a blood group,
component, positive integer quantity and required-by date, and optionally mark
the request **Emergency / STAT**. Dates use the application's configured time
zone and may be today or later. The server assigns a unique `REQ-` reference,
Pending status, hospital owner and submission event. Hospital users can list
and inspect only their own requests and change priority while Pending.

Staff and administrators open **Requisition Queue**. Its default filter is
Pending. STAT comes first, then oldest submission and primary key for stable
ordering. Staff can approve or reject; rejection requires a reason. Review and
priority forms include the current version so a stale form cannot overwrite a
new decision. Repeated or conflicting changes return HTTP 409.

Request detail displays requested/dispatched/remaining quantities and persistent
actor/timestamp/reason history. Domain services recheck the stored account's
role, activity and hospital approval; Django's `is_staff` flag alone grants no
clinical permission. Django admin exposes these records read-only.

## Live STAT alerts

Staff pages poll `GET /requisitions/stat-alerts/` immediately and every five
seconds while the page is visible. The alert links to the Pending review queue;
opening that link refreshes its rows. Background checks never reload review
forms. A four-second request timeout and visible failure message prevent silent
loss of alert updates. Unauthorized/expired sessions stop polling.

The alert uses the existing `alert-permanent` CSS hook so the global five-second
flash-message dismissal does not remove it. Polls do not renew session expiry:
`ActivitySessionMiddleware` delegates all ordinary requests to Django's session
middleware, but avoids saving an unchanged STAT-poll session. Actual page/form
activity still renews the existing 30-minute inactivity window; expired cookies
are cleared normally. The server's session expiry remains authoritative.

This implements the SRS's on-screen notification option; SMTP is not required for
STAT. Foreground notification latency is one poll interval plus request time.

## JSON interfaces

Use session cookies and Django CSRF tokens for mutations. Routes use trailing
slashes, consistently with the project's appointment/inventory APIs.

| Method | Route | Access and purpose |
|---|---|---|
| GET | `/api/requests/` | Own hospital requests; staff queue |
| POST | `/api/requests/` | Approved hospital submission |
| GET | `/api/requests/<pk>/` | Scoped detail with history |
| PATCH | `/api/requests/<pk>/priority/` | Owning hospital's Pending priority |
| POST | `/api/requests/<pk>/review/` | Staff/admin review |

Submission JSON: `bloodGroup`, `component`, `quantity`, `requiredBy` (date string),
and optional boolean `isStat`. Hospital identity/status are never client inputs.
Review JSON: `action` (`approve` or `reject`), optional text `reason`, integer
`version`. Priority JSON: boolean `isStat`, integer `version`.

Responses include numeric `id`, human-readable `requestId`, status, quantities,
version and timestamps. List results are paginated (25/page); `status` filters
accept the documented model status values. Unknown fields/malformed input return
400, wrong content type 415, missing authentication 401, forbidden roles 403,
foreign/missing records 404 and stale transitions 409. CSRF middleware also
returns 403 for invalid/missing CSRF credentials. All request responses are
non-cacheable. HTML templates escape stored review reasons.

## Integration contract for allocation/dispatch (#37)

`Requisition` has Pending, Approved, Partially Fulfilled, Fulfilled and Rejected
states. Staff approval records reviewer/time; it does not dispatch stock.
`RequisitionFulfilment` stores one actual dispatched `BloodUnit` per entry. Its
one-to-one constraint prevents counting a bag twice or against two requests.
Counts derive from these entries, not an editable fulfilled-quantity field.

After its own compatibility/override, reservation and stock-safety checks, the
dispatch service calls this hook inside the same outer database transaction:

```python
from requisitions.services import record_dispatched_units

record_dispatched_units(
    requisition.pk, actor=staff_user, unit_ids=[unit.pk for unit in dispatched_units],
    expected_version=requisition.version,
)
```

The hook verifies approval, distinct saved Bag IDs, Dispatched state, passed
serology, component, expiry and remaining quantity. It records the evidence and
an event, then derives partial/full status. It does not execute allocation,
compatibility matching, dispatch or receipt; those remain #36/#37/#32. There is
no public HTTP endpoint to fake a dispatch count. Validation/event failures roll
back the version, evidence and status together.

Transitions claim a version using a conditional write. SQLite does not supply
row locks through `select_for_update`; lock/unique conflicts produce a retryable
domain conflict rather than a second decision or duplicate count. Callers must
retry the entire outer operation after a competing transaction, not a fragment.

Events and fulfilment facts reject supported update/delete/upsert paths, and
history-bearing records are protected from deletion. This is per-request
history; the system-wide tamper-evident audit pipeline remains #47.

## Verification / traceability

| Requirement | Evidence |
|---|---|
| F-042–F-044 | Submission validation, unique references, approval/activity/role checks |
| F-045 | Audited approve/reject, mandatory reason, stale versions, real-bag partial/full counts |
| F-046 | Own-only HTML/API list/detail and event history |
| F-047 | Creation/priority changes and deterministic STAT-first queue |
| F-048 | Persistent staff alert, changing summary, bounded polling and idle-session preservation |

Automated cases live under `requisitions/tests/`, including rollback, duplicate
bags, unsafe stock, malformed JSON, XSS encoding, CSRF and session expiry.
Run `python manage.py test requisitions` and the full `python manage.py test`,
plus `flake8 .` and `python manage.py makemigrations --check --dry-run`.

Manual localhost verification used an isolated synthetic SQLite database:
hospital login/submission, B+ selection, staff queue, approval/history and live
alert updates. Existing account, collection and inventory records were not used.
