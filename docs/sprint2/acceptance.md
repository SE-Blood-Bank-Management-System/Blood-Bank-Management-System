# Sprint 2 integration and acceptance record — Issue #49

Client review date: **1 November 2026**. Baseline: `1d9be8d` on `main`.
This addendum updates the submitted SRS Sections 5/6/8, SAD interface inventory
and STP execution record. Original Deliverable 1 PDFs remain the design baseline.

## Outcome and evidence

The integrated synthetic workflow executes request → staff approval → recorded
cross-match → FEFO allocation → dispatch manifest → owning-hospital receipt.
Partial/full dispatch, unsafe/expired exclusion, permissions, available counts,
requisition reports and central hash-chain integrity are checked together in
`core.test_sprint2_integration`. The real browser demo also executes component
separation, CSV export and audit inspection through the running app.

- Full local regression: **419 tests passed in 929.949 seconds**, with production
  password hashing and the local TCP SMTP delivery test enabled. This run followed
  the component-compatibility fix. The initial sandboxed run could not open the
  SMTP socket; it was discarded and rerun with local network access.
- Subsequent search-query change: **15 focused tests passed** across integration
  and core tests; the new controlled-error logging acceptance test also passed.
  The final CI run discovers **421 tests** and is authoritative for the final PR.
- Business-logic statement coverage: see [the measured report](evidence/coverage.txt).
  The committed `.coveragerc` includes accounts, donors, appointments, inventory,
  requisitions and core application logic, including models/forms/services/views/
  authentication/middleware/audit/reports. Tests, migrations, admin registration,
  URL wiring, app registration and management commands are excluded. This is
  statement coverage, not a claim of branch coverage or complete clinical safety.
- `flake8 .`, migration drift check and a production-mode `check --deploy` pass.
  The deployment check uses synthetic environment values; it does not test a live
  certificate, reverse proxy or Internet endpoint.
- Committed synthetic unit/request/manifest/receipt data is reopened in a fresh
  Django process and compared by digest. See [persistence evidence](evidence/persistence.json).
  This is restart/reopen evidence, not a simulated power failure or crash-recovery test.

## Integration defects found and resolved

**INT-001 — component-policy mismatch (High):** allocation and FEFO suggestions
used RBC rules even when the component was plasma, while #36 cross-matching used
component-aware rules. This could reject a policy-compatible selection and allow
a policy-incompatible one without its required override. Allocation, suggestions
and inventory candidate labels now reuse `requisitions.compatibility`. A regression
tests both AB-plasma→O and O-plasma→AB against the existing academic component policy.
The full regression passed after this fix. No new transfusion policy was invented.

**INT-002 — repeated availability queries:** the public lookup issued one COUNT
for each blood group. It now aggregates all eight groups in one stock query; a
query-budget test verifies this while retaining zero-count groups. This improves
query cost but does **not** establish the 2-second concurrent-load requirement.

## NFR assessment — actual results

The workload uses an isolated Windows/Python 3.12/Django development server and
SQLite database, 50 distinct real session cookies and a small synthetic fixture.
Times cover HTTP request to complete response, not browser page rendering. No
password hashers or application security controls are weakened for these timings.
One burst of 50 requests is a local measurement, not a production capacity test.

| SRS requirement | Result | Evidence / limitation |
| --- | --- | --- |
| NF-001: search ≤2s, up to 50 users | **Fail locally** | Initial median/p95/max: 8.803/9.625/9.999s. Final after one-query aggregation: 5.550/6.324/6.669s. All 50 responses succeeded; timing limit failed. |
| NF-002: booking ≤3s | **Pass locally** | 10 real sequential JSON bookings: final median/p95/max 0.045/0.073/0.103s; all returned 201. |
| NF-003: 50 authenticated users ≤2s | **Pass locally** | 50 distinct sessions reading their protected appointment API: final median/p95/max 1.200/1.846/1.936s; all returned 200. Initial max 2.169s failed; both runs retained. |
| NF-004: ≥99% scheduled availability | **Blocked** | No agreed operating-hours window or monitored deployed service; a short local run cannot establish this. |
| NF-005: committed data across restart | **Pass for local reopen** | Fresh application process reads identical persisted unit/request/dispatch/receipt digest. |
| NF-006: timestamped error + stack trace | **Pass automated** | `core.test_nfr_reliability` triggers a real unhandled test-route error, checks logger exception information, timestamp formatting and a safe HTTP 500. |
| NF-007: unassisted first-time registration <5min | **Blocked** | No independent first-time participant; an automated walkthrough is not a usability study. |
| NF-008: keyboard and AA contrast | **Blocked for full acceptance** | Demo uses real keyboard selection and labelled controls. A complete primary-workflow keyboard/contrast audit has not been performed; no WCAG AA certification is claimed. |
| NF-009: clear validation failures | **Pass in automated scope** | Registration, request, receipt, security and report validation suites exercise field errors and invalid inputs. All possible errors have not been manually reviewed. |
| NF-010: modular/layered structure | **Pass review** | Domain services and ORM models are separate from HTML/JSON adapters; component policy is shared; reporting consumes service/data projections. No reporting rewrite was required for the policy fix. |
| NF-011: ≥60% business coverage | **Pass** | Measured statement coverage exceeds 60%; exact scope and per-module report retained. |
| NF-012: two latest Chrome/Firefox/Edge versions | **Blocked** | Actual demo runs in installed Brave/Chromium 156; the six required browser/version combinations are not available. Brave is not a substitute for that matrix. |
| NF-013: supported OS/runtime deployment | **Partial / Blocked broadly** | Windows/Python 3.12 runs locally; existing CI tests Linux/Python 3.11 and 3.12. Arbitrary-host deployment and macOS are not independently demonstrated. Django 5.2 requires Python ≥3.10. |
| NF-014: SQLite→multi-user RDBMS | **Blocked for migration proof** | ORM/interface review supports portability, but no PostgreSQL migration or concurrency run was executed. SQLite ignores row-level SELECT FOR UPDATE locks; do not infer PostgreSQL behaviour from SQLite tests. |
| NF-015: add location without module changes | **Pass architecture review** | Registry entries are data (`BloodBankLocation`); slot/location queries and inventory discovery consume them. Location-filtering tests are in the passing regression. The inventory location string remains a documented denormalization. |

Raw request-level timings: [initial run](evidence/nfr-initial.json) and
[final run](evidence/nfr-final.json). Reproduce with `demo/check_nfr.py` against a
separate `demo/run_sprint2.py` server on port 8773. Do not benchmark a production
database; the script creates synthetic users, sessions and bookings.

## Security, interfaces and acceptance limits

Authentication, hashing, role checks, input/escape handling, sessions, lockout,
SMTP delivery and tamper-evident audit tests are included in the full regression.
SR-008 remains **partially verified**: secure configuration and audit tests pass,
but end-to-end deployed TLS was not exercised. Hash chaining detects changes
relative to stored chain state; a database administrator able to rewrite the
whole chain is outside that guarantee. No external/WORM anchor was established.

See [interfaces, roles and state semantics](interfaces.md), the
[91-requirement RTM](requirements-traceability.csv), and the
[operator/user guide](user-guide.md). Implemented HTML workflows do not close
the unresolved SAD JSON-interface deviations.

## Owner review, protection and freeze handoff

- The scheduled development freeze was **30 October**. This integration and demo
  were performed on **1 November**, so an on-time freeze is not claimed.
- A teammate must independently review this PR and a repository owner must merge
  it. No independent review, owner merge, course acceptance or signature is
  represented as complete by this document.
- On inspection, the repository ruleset **Protect main branch** (ID 25422093)
  existed with enforcement **disabled**; classic branch-protection lookup returned
  HTTP 404. Owner action: enable the applicable ruleset, require PR review and both
  Python CI checks, and verify bypass policy. Permissions were not changed here.
- **PERF-001 (High, unresolved):** repeat NF-001 on the agreed deployment/runtime
  and representative fixture, investigate rendering/SQLite contention and meet
  the ≤2s threshold. Local query reduction alone is not a closure.
- Owner/evaluator must acknowledge remaining Blocked/Partial results and interface
  deviations, obtain missing deployment/usability/browser evidence, and record
  the accepted final commit/tag and actual freeze date after merge.

Overall disposition: **integrated functional build with passing regression;
conditional acceptance, not unconditional SRS/NFR completion**.
