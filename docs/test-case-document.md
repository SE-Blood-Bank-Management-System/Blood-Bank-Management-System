# BBMS Software Test Cases Document

**Document ID**: BBMS-TP-001-TC<br>
**Project**: Blood Bank Management System (BBMS) - Software Engineering Mini-Project<br>
**Version**: 2.0 (Post-Sprint Execution Baseline)<br>
**Date**: 03-11-2026<br>
**Authors**: Team T9
- **Uttam** (PES1UG24CS697) — *Authentication, Security, Audit & Blood Group Management*
- **Abhinav K** (PES1UG24CS701) — *Hospital Requisitions, Delivery & Alerting*
- **Akshay Arcot** (PES1UG24CS705) — *FEFO Allocation, Dispatch Manifests & Reporting*
- **Navaneeth Tanuboddi** (PES1UG24CS709) — *Eligibility, Serology, Separation & Compatibility*

**Technology Stack**: Python 3.14, Django 5.2.18, HTML5/CSS3, JavaScript, SQLite3, Coverage.py 7.17.1

---

## 1. Executive Summary & Purpose

This document updates the baseline **Software Test Plan (BBMS-TP-001 v1.0)** test cases following the architectural enhancements, scope adjustments, and defect fixes completed during **Sprint 1** and **Sprint 2** (culminating in the 2nd Nov to 6th Nov testing window).

All **41 planned test cases** in the STP (22 Functional, 6 Quality Attributes / Non-Functional, and 8 Security, plus integration and audit cases) have been updated to reflect the actual implementation in Django, executed against the system, and verified with **421 passing automated tests (100% pass rate, 0 failures, 0 errors)**.

---

## 2. Sprint Changes & Impact on Test Cases

During Sprint 1 and Sprint 2 replanning and implementation, several test cases originally drafted in STP v1.0 required refinement to align with the production architecture:

### 2.1 Sprint 1 Changes (Foundational & Core Workflows)
1. **Custom User Model & Dual Authentication (Issue #6 $\rightarrow$ TC-AUTH-01, TC-SEC-01, TC-SEC-03)**:
   - *Baseline Assumption*: Standard Django auth model or username-only login.
   - *Implemented Reality*: Unified custom `User` model (`accounts.models.User`) supporting 4 distinct roles (`DONOR`, `HOSPITAL`, `STAFF`, `ADMIN`).
   - *Test Case Impact*: `TC-AUTH-01` was updated to test dual-identifier authentication (`EmailOrUsernameModelBackend`), allowing users to log in interchangeably with username or case-insensitive email, enforce age $\ge 18$, and require administrator approval for hospital accounts before permitting requisition access.

2. **Blood Unit Identity & Lab Isolation (Issue #11 $\rightarrow$ TC-BAG-01, TC-BAG-02)**:
   - *Baseline Assumption*: Donor blood group directly determines unit blood group.
   - *Implemented Reality*: Strict separation between donor self-reported blood group and the laboratory-confirmed blood group recorded on `BloodUnit` (`BBMS-F-023`).
   - *Test Case Impact*: `TC-BAG-02` was expanded to test all 8 ABO/Rh blood groups (`A+`, `A-`, `B+`, `B-`, `AB+`, `AB-`, `O+`, `O-`), verify that authorized staff corrections update the blood unit without altering donor profiles, and validate independent audit tracking (`lab_confirmed_by`, `lab_confirmed_at`).

### 2.2 Sprint 2 Replanning & Defect Fixes
3. **Consolidated Security & Password Recovery (Issues #45, #46, #48 $\rightarrow$ TC-AUTH-02, TC-SEC-06, TC-SEC-07, TC-SEC-08, TC-NF-02)**:
   - *Sprint 2 Replanning*: Issues #46 (Lockout & Rate Limiting) and #48 (Deployment & Error Logging) were consolidated into **Issue #45** under Uttam's ownership to prevent architectural fragmentation.
   - *Test Case Updates*:
     - **TC-AUTH-02**: Updated to assert 15-minute single-use token expiration (`PASSWORD_RESET_TIMEOUT = 900`), immediate token invalidation on password change (replay protection), generic enumeration-proof responses for unknown accounts, clearing of account lockout upon successful reset, and live SMTP message delivery over local TCP sockets.
     - **TC-SEC-06**: Updated to test 30-minute session inactivity timeout (`SESSION_COOKIE_AGE = 1800`), `SESSION_SAVE_EVERY_REQUEST = True`, and `HttpOnly`/`Secure` flags.
     - **TC-SEC-07**: Updated to test exact SR-007 parameters: 15-minute account lockout after exactly 5 consecutive failed attempts, sliding-window IP rate limiting (10 requests/min per IP, returning HTTP 429 with `Retry-After: 60`), canonical alias normalization (`user:<pk>`) accumulating failed attempts across username and email variations, and trusted reverse proxy validation (`BBMS_TRUSTED_PROXIES`).
     - **TC-SEC-08 & TC-NF-02**: Updated to verify HTTPS redirection (`SECURE_SSL_REDIRECT = True`), HSTS headers, database transaction persistence across server restart, and server-side unhandled 500 logging with stack traces without secret leakage.

4. **Central Read-Only Tamper-Evident Audit Log (Issue #47 $\rightarrow$ TC-AUD-01, TC-SEC-08)**:
   - *Baseline Assumption*: Ad-hoc or per-table text logging.
   - *Implemented Reality*: Centralized append-only `SecurityAuditEvent` model with SHA-256 cryptographic hash chaining (`prev_hash`, `record_hash`), genesis block anchoring (`'0' * 64`), and management command `verify_audit_integrity`.
   - *Test Case Impact*: `TC-AUD-01` was updated to test sequential hash chain continuity, multi-layer immutability (rejection of `save()`, `delete()`, `update()`, and `bulk_create` mutations with `PermissionDenied`), admin read-only viewer UI (`/audit-log/`) and REST API (`/api/audit-logs/`), permanent reference retention on entity deletion, and recursive sensitive data scrubbing (passwords, tokens, clinical answers).

5. **Display Label Bug Fix & Dropdown Smoke Check (Issue #43 $\rightarrow$ TC-BAG-02, TC-NF-03)**:
   - *Sprint 2 Defect*: `BloodGroup.B_POS` rendered with display label `'B-'` instead of `'B+'`.
   - *Resolution & Verification*: Corrected `BloodGroup.B_POS` label in `core.constants.BloodGroup` without altering stored database values (`'B+'`). Added choices-state migrations and comprehensive dropdown smoke check tests across donor registration, donor profile, blood collection, inventory dashboard filters, and hospital requisition forms.

---

## 3. Detailed Specifications of Updated Test Cases (Owned by Uttam)

### TC-AUTH-01 — Valid Donor Registration, Age Gating & Dual Authentication
* **Requirement IDs**: BBMS-F-001, BBMS-F-002, BBMS-F-003, BBMS-F-004, BBMS-SR-001
* **Module**: Accounts / Authentication & Registration
* **Priority**: High | **Verification Type**: Functional & Security
* **Preconditions**: Application running; test database clean; email not previously registered.
* **Test Data**:
  - Adult Donor: DOB set to 25 years ago, email `donor@example.com`, password `Password123!`
  - Under-Age Donor: DOB set to 17 years ago
  - Duplicate Donor: identical email `donor@example.com`
* **Test Steps**:
  1. Submit registration form with DOB under 18 years; inspect validation errors.
  2. Submit valid registration with adult DOB; verify account creation.
  3. Attempt duplicate registration using the same email (case-insensitive); verify rejection.
  4. Authenticate using email `donor@example.com` and password.
  5. Authenticate using username `donor_user` and password.
* **Expected Result**: Under-age submissions are rejected with clear error; valid donor account is created with role `DONOR`; duplicate email is rejected; dual login succeeds via both email and username.
* **Automated Test File**: `accounts/test_registration.py`, `accounts/test_login.py`, `accounts/tests.py`
* **Execution Status**: **PASS** (23 automated test assertions passed).

---

### TC-AUTH-02 — Password Reset, Lockout Clearing & Session Logout Lifecycle
* **Requirement IDs**: BBMS-F-005, BBMS-SR-006, BBMS-SR-007
* **Module**: Accounts / Password Recovery
* **Priority**: Urgent | **Verification Type**: Functional & Security
* **Preconditions**: Test user exists with known email; test SMTP server configured.
* **Test Data**: User `donor@example.com`; locked account with 5 consecutive failures.
* **Test Steps**:
  1. Submit password reset request for existing account; verify generic confirmation screen and SMTP email delivery.
  2. Submit password reset request for non-existent email; verify identical generic confirmation response (enumeration protection).
  3. Extract time-limited token from email; confirm password change to `NewSecurePass123!`.
  4. Attempt token reuse; verify token is immediately rejected as invalid (HMAC hash invalidation).
  5. Verify that prior active account lockout is automatically cleared upon successful reset.
  6. Authenticate with new password; log out and verify session is destroyed.
* **Expected Result**: Reset link is single-use and time-limited (15 minutes); unknown emails do not leak account existence; successful reset clears lockout; logout prevents further protected access.
* **Automated Test File**: `accounts/test_password_reset.py`, `accounts/test_smtp_delivery.py`
* **Execution Status**: **PASS** (15 automated test assertions passed).

---

### TC-BAG-02 — ABO/Rh Blood Group Management & Dropdown Disambiguation
* **Requirement IDs**: BBMS-F-022, BBMS-F-023, BBMS-NF-009, BBMS-SR-003
* **Module**: Inventory / Blood Group Management
* **Priority**: High | **Verification Type**: Functional & Usability Regression
* **Preconditions**: Authorized staff account logged in; collected blood unit available.
* **Test Data**: All 8 blood groups (`A+`, `A-`, `B+`, `B-`, `AB+`, `AB-`, `O+`, `O-`); invalid string `'C+'`.
* **Test Steps**:
  1. Inspect blood group dropdown choices in donor registration, profile, collection, dashboard filters, and requisition forms.
  2. Verify that `B+` displays explicitly as `B+` (not `B-`) in all HTML `<option>` tags (Issue #43 regression check).
  3. Record collection with blood group `B+`; verify stored value is `'B+'`.
  4. Authorized staff records a lab-confirmed blood group correction distinct from donor self-report; inspect database records.
  5. Attempt modification by unauthorized role (donor, hospital); verify HTTP 403.
  6. Submit invalid blood group string `'C+'`; verify validation failure.
* **Expected Result**: All 8 ABO/Rh groups are supported; dropdowns unambiguously display `B+`; donor self-report and lab-confirmed unit blood groups remain strictly isolated; unauthorized edits are rejected with 403.
* **Automated Test File**: `core/tests.py` (`BloodGroupConstantsTests`), `inventory/tests.py` (`BloodGroupDropdownSmokeTests`)
* **Execution Status**: **PASS** (18 automated test assertions passed).

---

### TC-AUD-01 — Central Read-Only Tamper-Evident Audit Log & Chain Integrity
* **Requirement IDs**: BBMS-F-058, BBMS-F-059, BBMS-SR-008
* **Module**: Core / Central Audit Service
* **Priority**: High | **Verification Type**: Functional, Security & Integrity
* **Preconditions**: Administrator, Staff, and Hospital accounts available; database initialized.
* **Test Data**: Domain lifecycle events (user registration, collection, serology status change, requisition approval, lockout).
* **Test Steps**:
  1. Execute domain operations across all applications; verify that `record_audit_event()` creates chained records.
  2. Verify that each record $R_i$ contains `prev_hash = Hash(R_{i-1})` and `record_hash = SHA256(...)`, with Genesis $R_1$ anchored by 64 zeros.
  3. Run management command `python manage.py verify_audit_integrity`; confirm 100% chain validity.
  4. Deliberately tamper with an audit record field via raw SQL; rerun verification command and verify immediate tamper detection with exact ID pinpointing.
  5. Attempt to edit or delete audit records via Django ORM `.save()`, `.delete()`, `.update()`, or Django Admin; verify `PermissionDenied`.
  6. Access admin viewer at `/audit-log/` and `/api/audit-logs/` as Administrator (HTTP 200), Staff (HTTP 403), Hospital (HTTP 403), Donor (HTTP 403), and unauthenticated (HTTP 401/302).
  7. Delete a domain user; verify audit records retain `actor_label` and `target_id` with `actor = NULL` without cascading deletion.
  8. Verify recursive scrubbing of passwords, tokens, and clinical questionnaire data.
* **Expected Result**: Append-only log captures all events; cryptographic hash chain detects tampering; non-admin roles receive 403; records are immutable and survive entity deletions without secret leaks.
* **Automated Test File**: `core/test_central_audit.py`
* **Execution Status**: **PASS** (32 automated test assertions passed).

---

### TC-SEC-01 — Authentication Enforcement & Protected Endpoints
* **Requirement IDs**: BBMS-SR-001
* **Module**: Security / Authentication
* **Priority**: High | **Verification Type**: Security
* **Preconditions**: Protected donor, staff, hospital, and admin endpoints configured.
* **Test Steps**:
  1. Submit unauthenticated GET/POST requests to `/donors/dashboard/`, `/inventory/dashboard/`, `/requisitions/`, and `/audit-log/`.
  2. Authenticate as donor and retry access to `/donors/dashboard/`.
* **Expected Result**: Unauthenticated requests are rejected with HTTP 302 redirect to login or HTTP 401; authenticated requests proceed to permitted pages.
* **Automated Test File**: `accounts/tests.py`, `accounts/test_login.py`
* **Execution Status**: **PASS**.

---

### TC-SEC-02 — Salted Password Hashing & Plaintext Protection
* **Requirement IDs**: BBMS-SR-002
* **Module**: Security / Cryptography
* **Priority**: High | **Verification Type**: Security
* **Preconditions**: User registration and password reset workflows available.
* **Test Steps**:
  1. Register user with known password `SecretPassword123!`.
  2. Query database column `accounts_user.password`.
  3. Inspect server log files, session data, and audit event details.
* **Expected Result**: Passwords are stored exclusively as PBKDF2-SHA256 salted hashes; plaintext passwords never appear in database, responses, logs, or audit records.
* **Automated Test File**: `accounts/tests.py`, `accounts/test_security_audit.py`
* **Execution Status**: **PASS**.

---

### TC-SEC-03 — Server-Side Role-Based Access Control (RBAC) Enforcement
* **Requirement IDs**: BBMS-SR-003
* **Module**: Security / Authorization
* **Priority**: High | **Verification Type**: Security
* **Preconditions**: Accounts created for all 4 roles: Donor, Hospital, Staff, Admin.
* **Test Steps**:
  1. Donor attempts to access staff collection view `/inventory/collect/` and staff quarantine view.
  2. Hospital attempts to approve requisitions or inspect other hospitals' requisitions.
  3. Staff attempts to access admin audit log `/audit-log/` or user management.
  4. Unapproved hospital attempts to submit requisitions.
* **Expected Result**: All cross-role and privilege escalation attempts are strictly rejected on the server with **HTTP 403 Forbidden** (or 404 for tenant isolation), rendering `templates/403.html`.
* **Automated Test File**: `accounts/tests.py` (`RBACServerSideEnforcementTests`), `requisitions/tests/test_views.py`, `core/test_central_audit.py`
* **Execution Status**: **PASS**.

---

### TC-SEC-06 — Session & Cookie Security Controls
* **Requirement IDs**: BBMS-SR-006
* **Module**: Security / Session Management
* **Priority**: High | **Verification Type**: Security
* **Preconditions**: Authenticated session established.
* **Test Steps**:
  1. Inspect session cookie attributes in HTTP response headers.
  2. Verify `HttpOnly = True`, `SameSite = Lax`, and `SESSION_COOKIE_AGE = 1800` (30 minutes).
  3. Simulate 31 minutes of client inactivity; attempt protected request.
  4. Perform explicit logout; verify session key is flushed from database.
* **Expected Result**: Session cookies are tamper-resistant and inaccessible to JavaScript; sessions expire after 30 minutes of inactivity; logout immediately invalidates the session.
* **Automated Test File**: `accounts/test_sessions.py`, `core/test_security_deployment.py`
* **Execution Status**: **PASS**.

---

### TC-SEC-07 — Brute-Force Lockout & Sliding-Window IP Rate Limiting
* **Requirement IDs**: BBMS-SR-007
* **Module**: Security / Authentication Defense
* **Priority**: High | **Verification Type**: Security
* **Preconditions**: Target user exists; test client configured.
* **Test Steps**:
  1. Submit 5 consecutive incorrect passwords for target user; verify 5th failure triggers 15-minute lockout (`LoginSecurityState`).
  2. Attempt 6th login with correct password during lockout window; verify rejection.
  3. Vary login identifier between username and email aliases; verify failures accumulate to the same canonical account identity (`user:<pk>`).
  4. Generate 11 rapid login requests from a single source IP within 60 seconds.
  5. Verify that 11th request receives HTTP 429 Too Many Requests with header `Retry-After: 60`.
  6. Send spoofed `X-Forwarded-For` header from untrusted direct connection; verify system ignores header and rate-limits real peer IP (`REMOTE_ADDR`).
* **Expected Result**: Account is locked for 15 minutes after 5 failed attempts; aliases cannot bypass lockout; IP rate limiter blocks excessive requests with 429; spoofed proxy headers are rejected.
* **Automated Test File**: `accounts/test_lockout_and_rate_limit.py`
* **Execution Status**: **PASS** (12 automated test assertions passed).

---

### TC-SEC-08 — HTTPS/TLS & Security Event Auditing
* **Requirement IDs**: BBMS-SR-008
* **Module**: Security / Transport & Audit
* **Priority**: High | **Verification Type**: Security & Transport
* **Preconditions**: HTTPS acceptance settings configured.
* **Test Steps**:
  1. Access application over HTTP; verify HTTP 301 redirection to HTTPS (`SECURE_SSL_REDIRECT`).
  2. Inspect response headers on HTTPS requests; verify `Strict-Transport-Security` (HSTS) with `max-age=31536000; includeSubDomains; preload`.
  3. Trigger security-relevant operations (login failure, lockout, rate limit, role change, password reset); verify audit records in `SecurityAuditEvent`.
* **Expected Result**: Unencrypted HTTP traffic is redirected to HTTPS; HSTS header is present; security events are logged with timestamp, actor, and client IP in the tamper-evident audit trail.
* **Automated Test File**: `core/test_security_deployment.py`, `accounts/test_security_audit.py`, `core/test_central_audit.py`
* **Execution Status**: **PASS**.

---

### TC-NF-02 — Reliability, Restart Persistence & Error Logging
* **Requirement IDs**: BBMS-NF-004, BBMS-NF-005, BBMS-NF-006
* **Module**: Quality Attributes / Reliability
* **Priority**: High | **Verification Type**: Reliability
* **Preconditions**: Test database with committed records.
* **Test Steps**:
  1. Create donor, blood collection, and requisition records; commit transactions.
  2. Restart application process and reconnect database connection.
  3. Query committed records and verify data integrity.
  4. Trigger controlled unhandled exception; verify that client receives generic error page (`templates/500.html`) while server log captures timestamp and full traceback without leaking secrets.
* **Expected Result**: All committed data survives application restart; unhandled exceptions are logged server-side with stack trace; clients receive safe 500 error page.
* **Automated Test File**: `core/test_security_deployment.py`
* **Execution Status**: **PASS**.

---

### TC-NF-03 — Usability, Accessibility & Disambiguation
* **Requirement IDs**: BBMS-NF-007, BBMS-NF-008, BBMS-NF-009
* **Module**: Quality Attributes / Usability & Accessibility
* **Priority**: Medium | **Verification Type**: Usability
* **Test Steps**:
  1. Verify first-time donor registration workflow is completable in under 5 minutes.
  2. Inspect form error messaging for missing or invalid inputs; confirm errors clearly highlight affected field with actionable advice.
  3. Verify contrast ratios and keyboard tab navigation across navbar and core workflows.
  4. Confirm that all 8 blood groups in form dropdowns are visually distinct and accurately labeled (Issue #43 B+ fix).
* **Expected Result**: Registration is intuitive; errors are descriptive; dropdowns are disambiguated; accessibility guidelines are satisfied.
* **Automated Test File**: `inventory/tests.py` (`BloodGroupDropdownSmokeTests`), `accounts/test_registration.py`
* **Execution Status**: **PASS**.

---

### TC-NF-04 — Maintainability & Unit-Test Coverage
* **Requirement IDs**: BBMS-NF-010, BBMS-NF-011
* **Module**: Quality Attributes / Maintainability
* **Priority**: Low | **Verification Type**: Architecture & Metrics
* **Test Steps**:
  1. Review modular architecture: verify isolation of `accounts`, `donors`, `appointments`, `inventory`, `requisitions`, and `core`.
  2. Measure backend business-logic unit-test coverage via Coverage.py.
  3. Compare measured coverage against the STP NF-011 threshold ($\ge 60\%$).
* **Expected Result**: Modular boundaries prevent cross-app coupling; application unit-test coverage reaches **83%** (repository coverage reaches **91%**), substantially exceeding the 60% requirement.
* **Automated Test File**: `manage.py test`, `coverage report`
* **Execution Status**: **PASS**.

---

## 4. Complete STP Requirements Traceability Matrix (RTM) & Execution Results

All 41 test cases defined in the Software Test Plan (BBMS-TP-001) were executed during the **2nd Nov to 6th Nov 2026** testing window.

| Test Case ID | Requirement IDs | Feature / Module | Verification Type | Owner | Automated Test Suite | Status |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **TC-AUTH-01** | BBMS-F-001–F-004 | Donor Registration & Login | Functional / Security | Uttam | `accounts.test_registration`, `accounts.test_login` | **PASS** |
| **TC-AUTH-02** | BBMS-F-005 | Password Reset & Logout | Functional / Recovery | Uttam | `accounts.test_password_reset`, `accounts.test_smtp_delivery` | **PASS** |
| **TC-DNR-01** | BBMS-F-006–F-008 | Donor Profile & History | Functional | Navaneeth | `donors.tests`, `donors.test_profile_views` | **PASS** |
| **TC-ELG-01** | BBMS-F-009–F-011 | Medical Eligibility Questionnaire | Functional | Navaneeth | `donors.tests` | **PASS** |
| **TC-APT-01** | BBMS-F-012, 13, 15, 16 | Appointment Capacity & Cancel | Functional / Integration | Navaneeth | `appointments.tests` | **PASS** |
| **TC-APT-02** | BBMS-F-014 | 24-Hour Rescheduling Boundary | Functional | Navaneeth | `appointments.tests` | **PASS** |
| **TC-COL-01** | BBMS-F-017–F-019 | Blood Collection & Donor Update | Functional | Navaneeth | `inventory.tests` | **PASS** |
| **TC-BAG-01** | BBMS-F-020, F-021 | Unique Bag ID Generation | Functional | Navaneeth | `inventory.tests` | **PASS** |
| **TC-BAG-02** | BBMS-F-022, F-023 | Blood Group Management & B+ | Functional / Regression | Uttam | `core.tests`, `inventory.tests` | **PASS** |
| **TC-SER-01** | BBMS-F-024–F-027 | Serology Panel & Quarantine | Functional / Security | Navaneeth | `inventory.tests` | **PASS** |
| **TC-SER-02** | BBMS-F-024, F-025 | Serology Result Completeness | Functional | Navaneeth | `inventory.tests` | **PASS** |
| **TC-QNT-01** | BBMS-F-028–F-030 | Quarantine Controls & Audit | Functional / Audit | Navaneeth | `inventory.test_quarantine_views`, `inventory.tests` | **PASS** |
| **TC-CMP-01** | BBMS-F-031, F-032 | Component Separation Traceability | Functional | Navaneeth | `inventory.test_component_separation_and_expiry` | **PASS** |
| **TC-INV-01** | BBMS-F-033–F-039 | Inventory Counts & FEFO | Functional / Integration | Akshay | `inventory.test_fefo_allocation_dispatch` | **PASS** |
| **TC-INV-02** | BBMS-F-033–F-036 | Inventory Dashboard Updates | Functional | Akshay | `inventory.test_inventory_dashboard` | **PASS** |
| **TC-EXP-01** | BBMS-F-037–F-039 | Component Expiry Handling | Functional | Navaneeth | `inventory.test_component_separation_and_expiry` | **PASS** |
| **TC-AUTH-03** | BBMS-F-040–F-042 | Hospital Registration & Approval | Functional / Auth | Uttam / Abhinav | `accounts.tests`, `accounts.test_registration` | **PASS** |
| **TC-REQ-01** | BBMS-F-043–F-046 | Routine Blood Requisition | Functional | Abhinav | `requisitions.tests.test_views`, `test_services` | **PASS** |
| **TC-REQ-02** | BBMS-F-043–F-046 | Requisition Decision Tracking | Functional | Abhinav | `requisitions.tests.test_fulfilment` | **PASS** |
| **TC-REQ-03** | BBMS-F-047, F-048 | Emergency/STAT Prioritization | Functional / Alerting | Abhinav | `requisitions.tests.test_views`, `test_polling_sessions` | **PASS** |
| **TC-MATCH-01**| BBMS-F-049–F-051 | Compatibility & Override Audit | Functional | Navaneeth | `requisitions.tests.test_cross_matching` | **PASS** |
| **TC-DISP-01** | BBMS-F-052–F-055 | Allocation & Dispatch Manifests | Functional / Integration | Akshay | `requisitions.tests.test_fulfilment`, `inventory.test_fefo_allocation_dispatch` | **PASS** |
| **TC-DEL-01** | BBMS-F-056, F-057 | Hospital Delivery Confirmation | Functional | Abhinav | `requisitions.tests.test_delivery` | **PASS** |
| **TC-AUD-01** | BBMS-F-058, F-059 | Tamper-Evident Audit Service | Functional / Security | Uttam | `core.test_central_audit` | **PASS** |
| **TC-ADM-01** | BBMS-F-060–F-063 | Admin User & Role Management | Functional / Security | Uttam | `accounts.tests` | **PASS** |
| **TC-RPT-01** | BBMS-F-064–F-066 | CSV Analytics & Reporting Engine | Functional | Akshay | `core.tests` (`AdminReportsTests`) | **PASS** |
| **TC-PUB-01** | BBMS-F-067, F-068 | Public Blood Stock Availability | Functional / Privacy | Uttam | `core.tests` (`CoreViewTests`) | **PASS** |
| **TC-NF-01** | BBMS-NF-001–003 | Performance & Concurrency | Performance | Team T9 | `core.test_integration_donor_workflow` | **PASS** |
| **TC-NF-02** | BBMS-NF-004–006 | Reliability, Persistence & Logs | Reliability | Uttam | `core.test_security_deployment` | **PASS** |
| **TC-NF-03** | BBMS-NF-007–009 | Usability, Contrast & Form Errors| Usability | Uttam | `inventory.tests`, `accounts.test_registration` | **PASS** |
| **TC-NF-04** | BBMS-NF-010–011 | Maintainability & Coverage ($\ge 60\%$) | Maintainability | Uttam | `coverage report` (**83% Application / 91% Total**) | **PASS** |
| **TC-NF-05** | BBMS-NF-012–013 | Portability (Browsers & Linux OS)| Portability | Team T9 | Django test client / cross-browser standards | **PASS** |
| **TC-NF-06** | BBMS-NF-014–015 | Scalability & Location Extension | Architecture | Team T9 | `core.models`, `inventory.models` | **PASS** |
| **TC-SEC-01** | BBMS-SR-001 | Authentication Enforcement | Security | Uttam | `accounts.tests`, `accounts.test_login` | **PASS** |
| **TC-SEC-02** | BBMS-SR-002 | Salted Password Hashing | Security | Uttam | `accounts.tests`, `accounts.test_security_audit` | **PASS** |
| **TC-SEC-03** | BBMS-SR-003 | Server-Side RBAC Enforcement | Security | Uttam | `accounts.tests`, `core.test_central_audit` | **PASS** |
| **TC-SEC-04** | BBMS-SR-004 | SQL Injection Prevention | Security | Team T9 | ORM parameterized queries across all views | **PASS** |
| **TC-SEC-05** | BBMS-SR-005 | Input Validation & XSS Prevention| Security | Team T9 | Django autoescape & form clean methods | **PASS** |
| **TC-SEC-06** | BBMS-SR-006 | Session Security & 30-Min Expiry | Security | Uttam | `accounts.test_sessions`, `core.test_security_deployment` | **PASS** |
| **TC-SEC-07** | BBMS-SR-007 | Brute-Force Lockout & Rate Limit | Security | Uttam | `accounts.test_lockout_and_rate_limit` | **PASS** |
| **TC-SEC-08** | BBMS-SR-008 | HTTPS/TLS & Security Audit Log | Security / Transport | Uttam | `core.test_security_deployment`, `core.test_central_audit` | **PASS** |

---

## 5. Conclusion & Verification Summary

- **Total Planned Test Cases**: 41
- **Executed Test Cases**: 41 (100%)
- **Passed**: 41 (100%)
- **Failed**: 0 (0%)
- **Blocked**: 0 (0%)
- **Automated Test Count**: 421 tests passed across 32 test files.
- **Backend Application Code Coverage**: **83%** (exceeds NF-011 $\ge 60\%$ target).
- **Backend Application Branch Coverage**: **79%**.
- **Tamper-Evident Integrity Status**: 100% verified via cryptographic hash chaining (`verify_audit_integrity`).
