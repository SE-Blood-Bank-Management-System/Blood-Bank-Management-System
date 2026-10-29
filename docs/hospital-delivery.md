# Hospital tracking and delivery confirmation — Issue #32

Implements SRS BBMS-F-046, F-056 and F-057, SAD Dispatch/Delivery and
TC-REQ-02 / TC-DEL-01 on the existing #30 requisition and #37 dispatch records.

## Hospital workflow

1. Apply migrations with `python manage.py migrate`.
2. Sign in as an active, approved hospital and open **Hospital Portal**.
3. Open an owned requisition to see allocated Bag IDs, current unit states,
   dispatch manifests, dispatch staff/timestamps, and receipt history.
4. Under **Confirm receipt**, select only bags physically received and submit.
   A partial receipt leaves other dispatched bags awaiting acknowledgement.
5. Selected units become **Delivered**. The authenticated receiver account,
   username snapshot and server timestamp are retained for each bag. Staff can
   inspect this history, but hospital receipt requires the owning hospital.

Fulfilled / Partially Fulfilled describes quantities dispatched, not quantities
received. Receipt does not increase available inventory, release reservations,
alter dispatch manifests or change the request's fulfilment status.

## Architecture and API

`DeliveryConfirmation` is an append-only one-to-one record of a
`RequisitionFulfilment`, protected from duplicate receipts and deletion.
`confirm_receipt` validates active hospital ownership, claims the requisition
version and locks the current units inside a transaction. Every selected bag
must be backed by dispatch evidence for that request and still be Dispatched.
Any invalid bag, duplicate receipt, stale version or audit failure rolls back
the entire batch. A uniqueness constraint also prevents competing confirmations
from recording a second receipt. SQLite lock conflicts return a retryable 409.

Inventory's existing audited `BloodUnit.save(actor=...)` now permits the narrow
Dispatched → Delivered hospital transition only when the same transaction has
persisted that owner's receipt. Both `StatusChange` and `RequisitionEvent`
capture the authenticated actor. The future central audit viewer (#47) can
consume these records; this feature does not implement that separate issue.

- `GET /api/requests/{request_pk}/`: existing scoped detail now includes
  `allocations`, `dispatches` and `deliveries`. A delivery's `id` identifies its
  persisted fulfilment record, while `bagId` identifies the physical bag.
- `POST /api/deliveries/{delivery_id}/confirm/`: SAD delivery confirmation route.
  Send `Content-Type: application/json`, a valid session/CSRF token, and
  `{"version": <current request version>}`. The server selects bag and receiver
  from the scoped record and session, never from client identity fields.
  Returns the updated request detail; repeat/stale submissions return 409.
  Foreign/unknown delivery IDs return 404; disallowed roles return 403.
- `POST /requisitions/{request_pk}/receipt/`: CSRF-protected HTML batch action
  using checkbox `bag_ids` values and hidden `version`.

No new logistics subsystem or delivery-state copy of allocation records is
introduced. Allocation status retains dispatch evidence; the unit's current
status and receipt record describe hospital custody.

## Verification and traceability

| Requirement / test plan | Automated evidence |
| --- | --- |
| F-046 / TC-REQ-02 | Owned tracking detail includes bags, manifests, dispatch and receipt history; foreign requests are hidden. |
| F-056 / TC-DEL-01 | Authenticated receiver and server time; active approved owner only; partial and repeated receipt submissions. |
| F-057 / TC-DEL-01 | Dispatched → Delivered history with hospital actor; invalid mixed batches and audit failures roll back. |
| Dispatch integration | Real allocation → dispatch → receipt; fulfilment and available counts remain unchanged by receipt. |
| Integrity / access | Unique immutable receipt, stale versions, non-dispatched units, CSRF and forged identity fields. |

Run `python manage.py test requisitions.tests.test_delivery`, `flake8 .`,
`python manage.py makemigrations --check --dry-run`, and `python manage.py test`.
