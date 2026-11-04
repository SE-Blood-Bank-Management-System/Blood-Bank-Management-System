# Deliverable 3 — live browser and NFR verification

Owner: Abhinav K (@abhinavk0006). Execution: **4 November 2026**.
Application baseline: **`3adb416`** (merged owner test-case PR #63).
This follow-up executes available checks that the earlier test-case contribution
left as follow-ups. It does not introduce a new sprint or reassign other owners.

## Environment and interpretation

Real application: Django development server on port 8773, Windows/Python/SQLite,
with a fresh synthetic database outside the repository. These browser, load and
persistence checks did not use normal `db.sqlite3`. Secure cookie flags were disabled only by the existing loopback demo
runner; outbound email used its in-memory backend. No deployed TLS claim follows.

The load client is Python on the user's laptop sending real HTTP requests directly
to `127.0.0.1:8773`. The timings do not include the agent's browser connection,
clicking pace or screenshot delays. Interactive browser verification uses the
in-app browser separately. Fifty simultaneous requests differ materially from
opening a page once in a normal browser. Laptop load, power mode, development
server and SQLite contention affect measurements; a failed sample is not proof
that every run or deployment will fail.

The first load run completed before the full-suite coverage run began. Browser
connection setup was attempted during that first load run; this is a possible
background-load confound, so an additional run is retained after coverage finishes.
No power or system security settings were changed. These are small-fixture local
measurements, not production capacity or browser page-render benchmarks.

## Agent-assisted live browser checks

Two hostnames provided separate session cookies against the same local database:
staff `uttam` on `127.0.0.1`, hospital `abhinav` on `localhost`. Actions were performed
through actual form controls, not mocked screens or direct database state changes.
The browser observations are retained in
[browser-checks-20261104.json](evidence/browser-checks-20261104.json).

| Check | Actual observation | Disposition |
| --- | --- | --- |
| Live STAT notification | Hospital submits B+ RBC quantity 2. Staff page has hidden/zero alert at first, then shows one pending STAT request without reload. First hidden observation was 1.145s after submission click; first visible observation was 5.527s. | Pass observed functionality. These sampled bounds include tool/control overhead, not exact paint latency or proof of strict ≤5s. |
| Queue navigation | Live alert appears while queue rows remain static; Open review queue refreshes the list and shows the request. | Pass intended alert/link workflow; no automatic row refresh claimed. |
| Keyboard and review validation | Keyboard selects B+/RBC and Approve/Reject. Reject without reason shows the required-reason error with Pending retained. Corrected approval via Tab/Return records staff actor/note. | Pass sampled keyboard actions and validation; not complete keyboard coverage. |
| Allocation and partial dispatch | Compatible BAG-ABHINAV-01 is the earlier-expiring bag; allocation succeeds; dispatch creates MAN-20261104-6F05A7 for one unit. | Pass observed; unsafe comparison stock not offered in the FEFO candidates. |
| Hospital receipt | Space/Tab/Return confirms that bag. Tracking shows Delivered with abhinav/server time; request stays Partially Fulfilled, 2 requested/1 dispatched/1 outstanding. | Pass observed, including separation of custody from fulfilment. |
| Logout | Hospital logout returns anonymous home navigation and success message. | Pass observed. |
| Registration and field errors | Abhinav Navaneeth with DOB 2015-01-01 receives the under-age field error. Correcting to 1999-01-01 and re-entering password creates the account and opens donor dashboard. Non-secret form values are retained. | Pass observed validation; not an independent first-time usability study. |
| Profile and history | Save synthetic address and B+ via keyboard controls; profile displays stored values. History explicitly shows zero donations and separate medical-screening requirement. | Pass observed. |
| Quarantine and status history | One unsafe bag, 1.0 days in quarantine; history retains initial Quarantined status, uttam and timestamp. | Pass observed. |

The tested request is `REQ-E934D32BF7524B55A2C0560E16F2A34C`. These are synthetic
identities and records. The existing isolated fixture contains five blood units;
this is not a realistic inventory-size or clinical safety certification.

## Sampled text contrast

Computed rendered text/background colors were read from the registration page,
its under-age error state, and the live STAT alert. Alpha transparency was
composited before calculating sRGB relative luminance. The applicable normal-text
threshold is 4.5:1 per [W3C SC 1.4.3](https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum).

| Sample | Measured ratio | Sample result |
| --- | ---: | --- |
| Registration labels | 15.4263:1 | Pass |
| Muted registration helper text | 6.7811:1 | Pass |
| Under-age error / sign-in link | 4.5275:1 | Pass |
| Create Donor Account button | 4.5275:1 | Pass |
| STAT alert text/link | 10.2171:1 | Pass |

Raw colors, opacity and thresholds are in the browser JSON. Hover/disabled/focus
states, every route, all control boundaries, zoom/reflow and assistive technologies
were not exhaustively audited. **NF-008 remains partially verified**, not WCAG AA
certified. The assisted form completion does not establish NF-007's independent
first-time participant requirement.

## Load results

First run: [request-level evidence](evidence/nfr-20261104.json).

| Requirement / workload | Median | p95 | Maximum | Result |
| --- | ---: | ---: | ---: | --- |
| NF-001, 50 simultaneous availability searches, ≤2s | 11.007846s | 11.960902s | 12.296448s | Fail locally |
| NF-003, 50 authenticated appointment reads, ≤2s | 1.357980s | 2.326248s | 2.533463s | Fail locally |
| NF-002, 10 sequential real booking POSTs, ≤3s | 0.132199s | 0.157672s | 0.201292s | Pass locally |

Each of the fifty users has a distinct real authenticated session. Session setup
is outside the request timing. Booking samples create ten persisted appointments
using distinct donor sessions, CSRF and an isolated slot with capacity 60.
See JSON for every response status and duration. The load helper reports completed
measurements even when thresholds fail; its process exit code is not a Pass verdict.

## Repeat load and full-suite coverage

The second run was performed after coverage completed and the temporary test tabs
were closed, with no agent browser or test runner active in parallel. The power scheme read **Balanced**;
AC/battery-saver status could not be inspected. Background laptop workload was not
fully controlled. The helper added another 50 synthetic donors/sessions and ten
bookings to the same server/database; the intervening browser flow also created
the request/manifest/receipt and donor, and moved one unit to Delivered. This is
not an identical frozen-data repetition. Both runs are retained; neither result
is selectively discarded.

[Repeat request-level evidence](evidence/nfr-repeat-20261104.json):

| Workload | Median | p95 | Maximum | Result |
| --- | ---: | ---: | ---: | --- |
| NF-001 search | 6.929777s | 7.900875s | 8.226179s | Fail locally; HTTP [200] |
| NF-003 authenticated reads | 1.269418s | 2.054195s | 2.168112s | Fail locally; HTTP [200] |
| NF-002 bookings | 0.080970s | 0.106062s | 0.111267s | Pass locally; HTTP [201] |

The complete regression finished with **421 tests passed in 1303.322s**,
exit code 0. The isolated full-suite database is separate from the browser/load
database. The local TCP SMTP delivery test was included. Coverage used
`coverage run --branch manage.py test` and the committed `.coveragerc`:

- **Statement coverage: 87.55%**, 3671/4193 executable statements.
- **Branch coverage: 70.02%**, 920/1314 branch exits.
- Coverage.py's printed TOTAL combines statement and branch opportunities when
  branch mode is enabled; it must not be relabelled as statement-only coverage.
- The SRS business-logic statement threshold of 60% is met. Branch coverage is
  reported separately without inventing an additional course threshold.

Raw [coverage JSON](evidence/coverage-20261104.json),
[coverage text](evidence/coverage-20261104.txt), and
[verification summary](evidence/verification-summary-20261104.json) retain scope,
counts and results. Tests, migrations, admin/URL/app registration and management
commands are excluded exactly as specified in `.coveragerc`; all six business
applications are measured. This is a whole-suite business-code measurement, not
an assertion that unmeasured code or every SRS case passed.

A fresh production-mode `manage.py check --deploy` also returned no issues with
synthetic host/secret/SSL settings. See [output](evidence/deploy-check-20261104.txt).
This does not contact a deployed HTTPS endpoint.

### Anonymous comparison and ordinary browsing

A supplementary direct-HTTP check used no cookies against the same
`/availability/` page after the repeated acceptance workloads. One anonymous
request took **0.090243s**; a synchronized burst of 50 anonymous clients had
median/p95/max **0.633326/1.583410/1.604814s**, all HTTP 200.
[Raw comparison](evidence/anonymous-comparison-20261104.json) retains all timings.

This demonstrates why a normal anonymous page visit can feel fast while the
authenticated-session workload misses its target. It does not invalidate either
measurement or close NF-001/NF-003 for all supported users. The difference suggests
investigating authentication/session persistence and SQLite contention, but no
profiling was performed to establish a root cause. Browser render/network-proxy
time is not part of these direct loopback HTTP timings.

## Reliability and integrity

After the browser dispatch/receipt, a fresh Django application process reopened the
committed database and returned the same snapshot digest. The snapshot contains
**5 units, 1 request, 1 manifest and 1 receipt**; **21 audit records** verify with no
chain errors. [Persistence evidence](evidence/persistence-20261104.json) retains
the digest/counts. This verifies local process reopen, not an abrupt OS crash,
power failure, backup restoration, or monitored availability.

NF-006's actual unhandled-error logging test is included in the automated suite;
its controlled test-only route does not exist in the deployed URL configuration.

## Remaining evidence boundaries

| Requirement | What still requires a separate environment/person |
| --- | --- |
| NF-004 | Agreed operating hours and deployment monitoring to establish ≥99% uptime; a brief loopback probe is insufficient. |
| NF-007 | Independent first-time participant and recorded unassisted registration duration. Agent-assisted completion is not a substitute. |
| NF-008 | Complete keyboard/contrast/accessibility audit beyond the tested actions and samples. |
| NF-012 | Latest two versions each of Chrome, Firefox and Edge. Installed Chrome/Edge paths were found, but their browser connectors were unavailable; no Firefox installation was found at its standard path. The in-app engine does not prove this six-version matrix. |
| NF-013 | This run establishes the local Windows runtime only; prior CI evidence covers Linux Python 3.11/3.12, not arbitrary hosts. |
| NF-014 | Provisioned multi-user RDBMS and executed SQLite migration/concurrency scenarios. SQLite tests do not establish row-level locking. |
| SR-008 | Real deployed HTTPS certificate/proxy/transport checks; configuration tests and HTTP localhost do not prove TLS. |

NF-010/NF-015 retain their prior modularity/location review evidence, supplemented
by the complete regression run. No new live location-registry operation or separate
architecture experiment is claimed here.

## Reproduction

Run these from the repository root in separate terminals with development dependencies
installed; choose a new disposable synthetic database path:

```powershell
python demo/run_sprint2.py --database ../d3-checks.sqlite3 --port 8773
```

```powershell
python demo/check_nfr.py --database ../d3-checks.sqlite3 --output ../nfr-results.json
python demo/verify_persistence.py --database ../d3-checks.sqlite3 --output ../persistence-results.json
```

For the browser flow, follow the observed steps above using the fixture's hospital
abhinav and staff uttam accounts. For the full regression and coverage:

```powershell
python -m coverage run --branch manage.py test
python -m coverage report
python -m coverage json -o ../coverage-results.json
```

Do not run coverage, additional load tests or CPU-heavy jobs concurrently with a
performance measurement. Record power mode, background load and deployment/runtime
for future comparisons. Preserve failing runs when repeating the experiment.
