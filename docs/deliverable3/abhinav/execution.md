# Abhinav — scoped test execution record

Execution date: **4 November 2026** (Asia/Calcutta). Code baseline: **`076935a`**.
Scope: Deliverable 3, Abhinav's assigned features and #49 integration regressions.
Only documentation changes are made by this PR; no application or automated test
implementation changes are introduced.

## Actual result

**137 test methods passed in 74.513 seconds**, exit code **0**; failures **0**,
errors **0**, skipped **0**. All **59** catalogue rows map to exact test labels in
this run. A row may cover a parameterized test with multiple variants; 59 scenarios
and 137 test methods are different counts. No new manual/browser/NFR experiment
or coverage measurement is inferred from this result.

Environment: Windows, Python **3.12.14**, Django **5.2.18**,
SQLite isolated in-memory Django test database. Existing production password
hashing was retained. The history migration regression migrates a controlled test
fixture back/forward and restores graph leaf migrations; it does not modify the
normal application database.

The [machine-readable record](execution-results.json) lists each observed test
label, result, invocation, baseline, duration and original local log SHA-256.
Verbose synthetic application security logs are omitted from the committed evidence.
The captured runner footer was:

```text
Ran 137 tests in 74.513s

OK
```

## Results by module

| Module | Test methods | Result |
| --- | ---: | --- |
| `accounts.test_registration` | 15 | PASS |
| `accounts.test_login` | 9 | PASS |
| `accounts.test_sessions` | 8 | PASS |
| `donors.test_profile_views` | 11 | PASS |
| `donors.test_history_rules` | 8 | PASS |
| `donors.test_profile_api` | 11 | PASS |
| `inventory.test_quarantine_views` | 9 | PASS |
| `inventory.test_status_transitions` | 9 | PASS |
| `inventory.test_status_integrity` | 8 | PASS |
| `requisitions.tests.test_services` | 11 | PASS |
| `requisitions.tests.test_views` | 11 | PASS |
| `requisitions.tests.test_api` | 8 | PASS |
| `requisitions.tests.test_polling_sessions` | 2 | PASS |
| `requisitions.tests.test_delivery` | 12 | PASS |
| `core.test_sprint2_integration` | 3 | PASS |
| `core.test_nfr_reliability` | 1 | PASS |
| `inventory.test_status_migration` | 1 | PASS |

## Reproduce

From the repository root in PowerShell, after installing `requirements-dev.txt`:

```powershell
$testModules = Get-Content docs/deliverable3/abhinav/test-modules.txt
python manage.py test @testModules --verbosity 2
```

Individual rows can be rerun using their full dotted label, for example:

```text
python manage.py test accounts.test_registration.DonorRegistrationTests.test_birthday_boundary_and_future_dates
```

## Limits and team report handoff

This run includes service/model, request/client, permission and integration tests;
they should not all be presented as isolated unit tests. It is an owner-scoped
regression record, not completion of the entire STP or all four course reports.
Whole-project statement and branch coverage require their own full test runs and
retained coverage data/configuration. No branch coverage percentage is claimed.

Manual STAT refresh timing, usability/accessibility, six browser/version
combinations, monitored uptime, real deployed TLS and multi-user database migration
remain unverified by this run. Previous local search latency failed its target;
do not replace that failure with PASS because Django client tests succeeded.
See the [follow-up matrix](test-cases.md#manual-and-nfr-follow-up-cases-not-inferred-from-automated-passes)
and the [historical acceptance record](../../sprint2/acceptance.md).
