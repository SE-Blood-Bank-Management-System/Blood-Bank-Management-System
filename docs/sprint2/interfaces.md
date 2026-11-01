# Final state, role and interface addendum

## Roles and custody

| Actor | Permitted workflow |
| --- | --- |
| Public | Home/about, read-only blood availability, donor/hospital registration and password-reset request. |
| Donor | Own profile/history/eligibility and eligible appointment booking/reschedule/cancellation. |
| Approved hospital | Own requisitions, Pending priority changes, tracking and own dispatched-bag receipt confirmation. Foreign records are hidden. |
| Staff | Collection/testing/quarantine, component separation/expiry, request review, cross-match/justified override, allocation and dispatch. Hospital receipt is not a staff substitute. |
| Administrator | Clinical staff functions, account/approval administration, reports/CSV and read-only central audit. |

Unit lifecycle: Quarantined → Available after all required passing serology;
failed testing → Discarded. Safe whole blood → Separated when child components
are created, preserving parent Bag ID traceability and collection-based expiry.
Available → Allocated → Dispatched → Delivered; expiry processing excludes
overdue stock. Issue #14's structured `StatusChange` history is retained.

Requisition lifecycle: Pending → Approved or Rejected (reason mandatory).
Dispatch evidence derives Partially Fulfilled / Fulfilled from actual unique bags.
Receipt changes custody, not fulfilment counts or available-stock totals.
Per-request version claims and transactions reject stale/conflicting mutations.
SQLite database locks may surface as retryable conflicts; production concurrency
still needs a multi-user database/deployment test.

The central audit store records security and domain events using append-only ORM
guards and SHA-256 chain verification. Views are read-only/admin-only. This does
not replace deployment log retention, backups or an independent integrity anchor.

## Retained SAD differences — unresolved, not silently implemented

Paths below are representative; retain the actual trailing-slash contract in the
existing feature docs. Do not POST to a slashless alias expecting an automatic
redirect to preserve a request body.

| SAD design endpoint | Actual interface / remaining deviation |
| --- | --- |
| POST `/api/auth/register` | Donor HTML form `/accounts/register/donor/`; standalone JSON adapter absent. |
| POST `/api/auth/login`, `/api/auth/logout` | Session/CSRF HTML login/logout under `/accounts/`; standalone JSON adapters absent. |
| POST `/api/auth/password-reset/request` | HTML recovery flow under `/accounts/password-reset/`; separate design JSON adapter absent. |
| POST `/api/hospitals/register` | HTML `/accounts/register/hospital/`; administrator approval is still required. Separate JSON adapter absent. |
| POST `/api/collections` | Staff HTML `/inventory/collection/record/`; standalone JSON collection creation absent. |
| GET `/api/public/availability` | Public HTML `/availability/`; separate JSON lookup absent. |
| POST `/api/requests/{id}/allocate` | Implemented `/api/requisitions/{id}/allocate/`; path differs from SAD. |
| POST `/api/dispatch` | Implemented `/api/requisitions/{id}/dispatch/` and `/api/manifests/{manifest_id}/`; path/payload layout differs. |
| POST `/api/deliveries/{id}/confirm` | Implemented with trailing slash. ID is a persisted fulfilment record, not Bag ID; request detail returns the delivery IDs. |
| GET `/api/audit` | Implemented `/api/audit-logs/` and HTML `/audit-log/`; design alias absent. |
| GET `/api/reports/{kind}.csv` | Actual downloads `/reports/inventory/csv/`, `/reports/donations/csv/`, `/reports/requisitions/csv/`; design aliases absent. |
| Donor self-service | `/api/donors/me`, `/api/donors/me/donations`, `/api/donors/me/eligibility` intentionally have no trailing slash. |

Request creation, detail, priority and cross-match use `/api/requests/` routes.
Session cookies and CSRF remain enabled; there is no new JWT/token subsystem.
Unified `accounts.User` contains donor/hospital attributes instead of the SAD's
separate donor-profile table. `BloodBankLocation` is relational for appointments;
unit storage location is a string. Dynamic default slot creation is retained.

These are documented adapters/deviations, not a claim that every submitted REST
design endpoint exists. Expanding authentication/collection/public JSON APIs was
explicitly excluded from the compact Sprint 2 plan.
