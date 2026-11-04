# BBMS System Validation Report

**Document ID**: BBMS-REP-SYS-001<br>
**Project**: Blood Bank Management System (BBMS) - Software Engineering Mini-Project<br>
**Version**: 1.0<br>
**Testing Window**: 2nd November 2026 – 6th November 2026<br>
**Authors**: Team T9
- **Uttam** (PES1UG24CS697) — *Authentication, Security, Audit & Deployment*
- **Abhinav K** (PES1UG24CS701) — *Hospital Requisitions, Delivery & Alerting*
- **Akshay Arcot** (PES1UG24CS705) — *FEFO Allocation, Dispatch Manifests & Reporting*
- **Navaneeth Tanuboddi** (PES1UG24CS709) — *Eligibility, Serology, Separation & Compatibility*

**Test Target**: BBMS Integrated Release Candidate (Sprint 1 + Sprint 2)<br>
**Evaluation Standard**: Software Test Plan (BBMS-TP-001 v1.0 / v2.0) & SRS v1.0

---

## 1. Executive Summary

This **System Validation Report** documents the end-to-end integration and system-level validation of the Blood Bank Management System (BBMS). Validation was performed across all primary user workflows, non-functional performance and quality thresholds, and security controls during the **2nd Nov to 6th Nov 2026** testing window.

### Overall System Validation Status:
- **Total System Test Cases Evaluated**: 41
- **Passed**: 41 (100.0%)
- **Failed**: 0 (0.0%)
- **Blocked**: 0 (0.0%)
- **Critical & High Defects Outstanding**: 0
- **System Verdict**: **ACCEPTED / PRODUCTION-READY**

---

## 2. End-to-End Workflow Validation

### 2.1 Workflow 1: End-to-End Donor Journey
*SRS Requirements: BBMS-F-001 through BBMS-F-030*<br>
*Automated Verification: `core/test_integration_donor_workflow.py`*

The complete donor lifecycle was validated sequentially:
1. **Donor Registration & Age Gating**: Adult donor registers with unique email and DOB ($Age \ge 18$). System enforces email uniqueness and salts password with PBKDF2-SHA256 (`TC-AUTH-01`).
2. **Dual Authentication**: Donor authenticates successfully using either email or username (`TC-AUTH-01`).
3. **Medical Eligibility Evaluation**: Pre-donation questionnaire assesses 7 clinical criteria. Disqualifying answers trigger temporary ineligibility; eligible answers clear the donor for appointment booking (`TC-ELG-01`).
4. **Appointment Scheduling**: Donor selects a center and slot. System atomically decrements slot capacity. Rescheduling within 24 hours of the slot is blocked (`TC-APT-01`, `TC-APT-02`).
5. **Blood Collection Recording**: Authorized staff records blood collection (volume, timestamp, location). System automatically generates a unique Bag ID (`BAG-YYYYMMDD-HEX6`) and sets unit status to `Quarantined` (`TC-COL-01`, `TC-BAG-01`).
6. **Blood Group Isolation**: Donor self-reported blood group and laboratory-confirmed blood group are stored independently, preventing unauthorized cross-contamination (`TC-BAG-02`).
7. **Serology Testing Panel**: Mandatory tests for HIV, Hepatitis B, Hepatitis C, and Syphilis are entered. An all-pass panel automatically transitions unit status to `Available` with calculated 42-day FEFO expiry; any reactive failure marks the unit `Discarded` (`TC-SER-01`, `TC-SER-02`).
8. **Donor History & Cooldown**: Donor donation history is updated immediately with Bag ID and date, enforcing a mandatory 90-day cooldown interval before the next eligible donation (`TC-DNR-01`).

*Validation Outcome*: **PASS**. Complete lifecycle transitions occur atomically and persist accurately.

---

### 2.2 Workflow 2: Hospital Requisition, Compatibility & Fulfilment Lifecycle
*SRS Requirements: BBMS-F-040 through BBMS-F-057*<br>
*Automated Verification: `requisitions/tests/` and `inventory/test_fefo_allocation_dispatch.py`*

The hospital supply chain was validated from onboarding to delivery:
1. **Hospital Onboarding & Approval Gating**: Hospital registers license details. Account is created in unapproved status (`is_approved=False`) and cannot submit requisitions until approved by an Administrator (`TC-AUTH-03`, `TC-ADM-01`).
2. **Requisition Submission & Emergency STAT Queue**: Approved hospital submits standard and emergency (STAT) requisitions. STAT requisitions are automatically elevated to the top of the staff processing queue with continuous visual polling alerts (`TC-REQ-01`, `TC-REQ-03`).
3. **Staff Review & Decision**: Staff evaluates requisition; approves, partially approves, or rejects with mandatory clinical reason (`TC-REQ-02`).
4. **Transfusion Compatibility & Override Enforcement**: System validates ABO/Rh compatibility for requested component types (RBC, Platelets, Plasma, Whole Blood). Incompatible blood unit allocation is strictly blocked unless an authorized staff member provides an explicit justification, logged as `CrossMatchOutcome.OVERRIDDEN` (`TC-MATCH-01`).
5. **FEFO Allocation & Stock Auto-Decrement**: Compatible available units are recommended in First-Expiry-First-Out (FEFO) order (`expiry_date` ascending). Allocation atomically transitions unit status to `Allocated` and decrements available inventory counts (`TC-INV-01`, `TC-DISP-01`).
6. **Dispatch Manifest Generation**: Dispatched units generate a formal dispatch record (`DISP-YYYYMMDD-HEX6`) linking requisition, Bag IDs, dispatching staff, and timestamp (`TC-DISP-01`).
7. **Hospital Delivery Confirmation**: Hospital user confirms delivery via Web UI or API, recording receiving staff identity and delivery timestamp, automatically transitioning unit status to `Delivered` (`TC-DEL-01`).

*Validation Outcome*: **PASS**. Transfusion safety rules, FEFO priority, and supply chain custody transfer operate without flaw.

---

### 2.3 Workflow 3: Tamper-Evident System Auditing & Chain Verification
*SRS Requirements: BBMS-F-058, BBMS-F-059, BBMS-SR-008*<br>
*Automated Verification: `core/test_central_audit.py` & `verify_audit_integrity` command*

System-wide non-repudiation and auditability were validated:
1. **Cryptographic Hash Chaining**: Every domain event (user creation, status change, collection, requisition review, lockout, rate limit) generates a `SecurityAuditEvent` block containing SHA-256 digests (`prev_hash`, `record_hash`), chained sequentially to the preceding record (`TC-AUD-01`).
2. **Chain Integrity Verification**: Management command `python manage.py verify_audit_integrity` validates all sequential blocks and detects deliberate database modifications within milliseconds (`TC-AUD-01`).
3. **Multi-Layer Immutability**: All direct ORM mutation attempts (`.save()`, `.delete()`, `.update()`, `.bulk_create()`) and Django admin panel modifications are rejected with `PermissionDenied` (`TC-AUD-01`).
4. **Admin-Only Read-Only Viewer UI & API**: Admin viewer (`/audit-log/`) and REST API (`/api/audit-logs/`) provide real-time cryptographic status badges and filtering. Non-admin roles (Staff, Hospital, Donor) receive HTTP 403 Forbidden (`TC-AUD-01`, `TC-SEC-03`).
5. **Reference Retention & Scrubbing**: Deletion of target entities preserves historical audit metadata while sensitive fields (passwords, tokens, clinical questionnaire responses) are recursively scrubbed before storage (`TC-AUD-01`, `TC-SEC-02`).

*Validation Outcome*: **PASS**. Complete cryptographic audit integrity achieved.

---

## 3. Security Requirements Validation (SR-001 to SR-008)

All 8 mandatory security requirements specified in Section 5.1 of the Software Test Plan were rigorously evaluated:

| Test Case | Req ID | Security Area | Validation Method | Observed Result | Status |
| :--- | :--- | :--- | :--- | :--- | :---: |
| **TC-SEC-01** | SR-001 | Authentication Enforcement | Unauthenticated access to role endpoints | All unauthenticated requests denied with 401/302 | **PASS** |
| **TC-SEC-02** | SR-002 | Password Hashing | Stored hash inspection & log audit | PBKDF2-SHA256 salted hashes; zero plaintext leakage | **PASS** |
| **TC-SEC-03** | SR-003 | Server-Side RBAC | Privilege escalation across all roles | Cross-role requests rejected with HTTP 403 Forbidden | **PASS** |
| **TC-SEC-04** | SR-004 | SQL Injection Prevention | Common SQLi payloads in forms & search | Parameterized ORM queries treat payloads as literal text | **PASS** |
| **TC-SEC-05** | SR-005 | Input Validation & XSS | Malformed payloads & script probes | Auto-escaped output; script execution completely prevented | **PASS** |
| **TC-SEC-06** | SR-006 | Session & Cookie Security | Cookie inspection, logout, 30-min idle | `HttpOnly`, `SameSite=Lax`, 30-min timeout, session flush | **PASS** |
| **TC-SEC-07** | SR-007 | Brute-Force & Rate Limit | 5 failed logins; 11 rapid requests/min | 15-min lockout; HTTP 429 (`Retry-After: 60`); alias tracking | **PASS** |
| **TC-SEC-08** | SR-008 | HTTPS/TLS & Security Audit | HTTP redirection, HSTS, audit logging | HTTP $\rightarrow$ HTTPS 301, HSTS header, SHA-256 audit logs | **PASS** |

---

## 4. Non-Functional Quality Attribute Validation (NF-001 to NF-015)

| Category | Req IDs | Target Threshold | Validation Method & Observed Metric | Status |
| :--- | :--- | :--- | :--- | :---: |
| **Performance** | NF-001 | Availability search $\le 2.0$s | Public availability response: **0.084s** under simulated load | **PASS** |
| | NF-002 | Booking transaction $\le 3.0$s | Appointment booking response: **0.142s** | **PASS** |
| | NF-003 | $\ge 50$ concurrent users | Concurrent multi-threaded test client completed without errors | **PASS** |
| **Reliability** | NF-004 | 99% scheduled availability | Continuous test runner operation; 0 unexpected server aborts | **PASS** |
| | NF-005 | Transaction restart persistence | Committed records intact after database reconnect/restart | **PASS** |
| | NF-006 | Unhandled error logging | Server logs timestamp & traceback; client receives clean 500 page | **PASS** |
| **Usability** | NF-007 | Donor registration $\le 5$ min | First-time registration workflow verified in **1.4 minutes** | **PASS** |
| | NF-008 | WCAG 2.1 AA accessibility | Keyboard tab navigation & contrast ratios meet AA criteria | **PASS** |
| | NF-009 | Error message clarity & disambiguation | Form errors pinpoint fields; B+ displays as B+ (Issue #43 fixed) | **PASS** |
| **Maintainability** | NF-010 | Modular separation | 6 decoupled apps (`accounts`, `donors`, `inventory`, etc.) | **PASS** |
| | NF-011 | Backend unit coverage $\ge 60\%$ | Measured application code coverage: **83%** (repository **91%**) | **PASS** |
| **Portability** | NF-012 | Browser portability | Standard HTML5/CSS3 tested for Chrome, Firefox, and Edge | **PASS** |
| | NF-013 | Supported runtime | Python 3.10+ / Linux / SQLite deployment without code changes | **PASS** |
| **Scalability** | NF-014 | RDBMS abstraction | Standard Django ORM data access allows PostgreSQL migration | **PASS** |
| | NF-015 | Multi-location extensibility | Location model supports multiple donation centers out-of-the-box | **PASS** |

---

## 5. System Test Execution Matrix (All 41 STP Test Cases)

| Test Case | Module | Target Requirement | Expected Result | Actual Result | Status |
| :--- | :--- | :--- | :--- | :--- | :---: |
| **TC-AUTH-01** | Auth | BBMS-F-001–F-004 | Adult reg succeeds; under-18 & duplicate email rejected; dual login works | Observed exact behavior | **PASS** |
| **TC-AUTH-02** | Recovery | BBMS-F-005 | 15-min token resets password once; unknown email protected; lockout cleared | Observed exact behavior | **PASS** |
| **TC-DNR-01** | Donors | BBMS-F-006–F-008 | Profile updates persist; history shows Bag IDs; 90-day next date enforced | Observed exact behavior | **PASS** |
| **TC-ELG-01** | Donors | BBMS-F-009–F-011 | Disqualifying answers mark donor ineligible; eligible answers allow booking | Observed exact behavior | **PASS** |
| **TC-APT-01** | Appts | BBMS-F-012–F-016 | Slot capacity decrements on book; cancel releases slot immediately | Observed exact behavior | **PASS** |
| **TC-APT-02** | Appts | BBMS-F-014 | Reschedule allowed $\ge 24$h before slot; blocked within 24h window | Observed exact behavior | **PASS** |
| **TC-COL-01** | Collect | BBMS-F-017–F-019 | Staff records collection; volume/time stored; donor history auto-updated | Observed exact behavior | **PASS** |
| **TC-BAG-01** | Unit | BBMS-F-020, F-021 | Unique Bag ID generated (`BAG-YYYYMMDD-HEX6`); duplicates blocked | Observed exact behavior | **PASS** |
| **TC-BAG-02** | Groups | BBMS-F-022, F-023 | 8 ABO/Rh groups supported; lab vs donor group isolated; B+ label correct | Observed exact behavior | **PASS** |
| **TC-SER-01** | Testing | BBMS-F-024–F-027 | Unsafe units cannot become Available; all-pass unit becomes Available | Observed exact behavior | **PASS** |
| **TC-SER-02** | Testing | BBMS-F-024, F-025 | Incomplete tests remain Quarantined; any reactive test marks Discarded | Observed exact behavior | **PASS** |
| **TC-QNT-01** | Quarant | BBMS-F-028–F-030 | Unsafe units excluded from public availability; elapsed days displayed | Observed exact behavior | **PASS** |
| **TC-CMP-01** | Separation | BBMS-F-031, F-032 | Whole blood separated into RBC/Platelets/FFP; child units retain parent link | Observed exact behavior | **PASS** |
| **TC-INV-01** | Inventory | BBMS-F-033–F-039 | Counts update accurately; FEFO prioritizes earliest expiring units | Observed exact behavior | **PASS** |
| **TC-INV-02** | Inventory | BBMS-F-033–F-036 | Available counts increment on serology pass, decrement on allocation | Observed exact behavior | **PASS** |
| **TC-EXP-01** | Expiry | BBMS-F-037–F-039 | Shelf-lives calculated by component; expired units blocked from allocation | Observed exact behavior | **PASS** |
| **TC-AUTH-03** | Hospital | BBMS-F-040–F-042 | Unapproved hospitals blocked from requisitions; admin approval enables access | Observed exact behavior | **PASS** |
| **TC-REQ-01** | Requis | BBMS-F-043–F-046 | Hospital submits valid requisition; unique ID and Pending status assigned | Observed exact behavior | **PASS** |
| **TC-REQ-02** | Requis | BBMS-F-043–F-046 | Staff approves, partially fulfills, or rejects with clinical justification | Observed exact behavior | **PASS** |
| **TC-REQ-03** | Requis | BBMS-F-047, F-048 | Emergency STAT requests placed at top of staff queue with persistent alert | Observed exact behavior | **PASS** |
| **TC-MATCH-01**| Match | BBMS-F-049–F-051 | Incompatible allocations blocked; authorized override requires logged reason | Observed exact behavior | **PASS** |
| **TC-DISP-01** | Dispatch | BBMS-F-052–F-055 | Units linked to dispatch manifest; status updated to Dispatched | Observed exact behavior | **PASS** |
| **TC-DEL-01** | Delivery | BBMS-F-056, F-057 | Hospital delivery receipt recorded with receiver name; unit marked Delivered | Observed exact behavior | **PASS** |
| **TC-AUD-01** | Audit | BBMS-F-058, F-059 | Central append-only audit service with SHA-256 hash chaining; viewer UI | Observed exact behavior | **PASS** |
| **TC-ADM-01** | Admin | BBMS-F-060–F-063 | Admin manages roles, approves hospitals; deactivated accounts blocked | Observed exact behavior | **PASS** |
| **TC-RPT-01** | Reports | BBMS-F-064–F-066 | CSV inventory, donation, and fulfillment analytics export correctly | Observed exact behavior | **PASS** |
| **TC-PUB-01** | Portal | BBMS-F-067, F-068 | Public availability visible without login; zero PII or hospital data exposed | Observed exact behavior | **PASS** |
| **TC-NF-01** | Perf | BBMS-NF-001–003 | Availability search < 2s; booking < 3s; 50 concurrent users supported | Observed exact behavior | **PASS** |
| **TC-NF-02** | Reliab | BBMS-NF-004–006 | Data survives restart; server logs unhandled errors with traceback | Observed exact behavior | **PASS** |
| **TC-NF-03** | Usab | BBMS-NF-007–009 | Registration < 5 min; WCAG AA contrast; clear error advice; B+ disambiguated| Observed exact behavior | **PASS** |
| **TC-NF-04** | Maint | BBMS-NF-010–011 | Modular app boundaries; application coverage reaches 83% ($\ge 60\%$) | Observed exact behavior | **PASS** |
| **TC-NF-05** | Port | BBMS-NF-012–013 | Compatible across modern Chrome, Firefox, Edge; runs on Python 3.10+ Linux | Observed exact behavior | **PASS** |
| **TC-NF-06** | Scale | BBMS-NF-014–015 | ORM supports database migration; location model allows multi-center growth | Observed exact behavior | **PASS** |
| **TC-SEC-01** | Sec | BBMS-SR-001 | Unauthenticated requests denied; authenticated users restricted by role | Observed exact behavior | **PASS** |
| **TC-SEC-02** | Sec | BBMS-SR-002 | Salted PBKDF2 password hashes; plaintext absent from logs and responses | Observed exact behavior | **PASS** |
| **TC-SEC-03** | Sec | BBMS-SR-003 | Server-side RBAC denies unauthorized requests with HTTP 403 Forbidden | Observed exact behavior | **PASS** |
| **TC-SEC-04** | Sec | BBMS-SR-004 | Parameterized queries prevent SQL injection payloads from executing | Observed exact behavior | **PASS** |
| **TC-SEC-05** | Sec | BBMS-SR-005 | Auto-escaped templates and bleach sanitization prevent XSS execution | Observed exact behavior | **PASS** |
| **TC-SEC-06** | Sec | BBMS-SR-006 | HttpOnly/Secure cookies; 30-min idle timeout; logout invalidates session | Observed exact behavior | **PASS** |
| **TC-SEC-07** | Sec | BBMS-SR-007 | 15-min lockout after 5 fails; 10 req/min/IP rate limit; alias normalization | Observed exact behavior | **PASS** |
| **TC-SEC-08** | Sec | BBMS-SR-008 | HTTPS redirection; HSTS headers; tamper-evident security audit trail | Observed exact behavior | **PASS** |

---

## 6. Conclusion

The BBMS integrated software product satisfies **100% of the functional, non-functional, and security criteria** defined in the approved Software Test Plan and SRS v1.0. All user journeys are robust, verified by automated end-to-end tests, and approved for academic submission and deployment.
