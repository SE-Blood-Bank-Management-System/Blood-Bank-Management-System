# BBMS Unit Test Report

**Document ID**: BBMS-REP-UNIT-001<br>
**Project**: Blood Bank Management System (BBMS) - Software Engineering Mini-Project<br>
**Version**: 1.0<br>
**Testing Window**: 2nd November 2026 – 6th November 2026<br>
**Authors**: Team T9
- **Uttam** (PES1UG24CS697)
- **Abhinav K** (PES1UG24CS701)
- **Akshay Arcot** (PES1UG24CS705)
- **Navaneeth Tanuboddi** (PES1UG24CS709)

**Execution Tool**: Django Test Runner (`python manage.py test`)<br>
**Runtime**: Python 3.14.7, Django 5.2.18, SQLite3 in-memory test runner

---

## 1. Executive Summary

During the test execution window of **2nd Nov to 6th Nov 2026**, the complete BBMS automated test suite was executed against the consolidated Sprint 1 and Sprint 2 codebase.

### Execution Results:
```
======================================================================
Ran 421 tests in 107.782s

OK (0 failures, 0 errors, 0 skipped)
Pass Rate: 100.0%
======================================================================
```

Every functional requirement, security control, and quality attribute defined in the **Software Requirements Specification (SRS v1.0)** and **Software Test Plan (STP v1.0 / BBMS-TP-001)** has passed automated verification without defects.

---

## 2. Test Execution Breakdown by Application

The test suite spans **32 automated test modules** across all 6 applications:

```
+----------------+------------+---------------+--------+--------+----------+
| Application    | Test Files | Tests Planned | Passed | Failed | Duration |
+----------------+------------+---------------+--------+--------+----------+
| accounts       |     8      |      114      |  114   |   0    |  28.4s   |
| appointments   |     1      |       28      |   28   |   0    |   7.2s   |
| donors         |     4      |       32      |   32   |   0    |   8.1s   |
| inventory      |     7      |      112      |  112   |   0    |  29.6s   |
| requisitions   |     7      |       87      |   87   |   0    |  22.1s   |
| core           |     5      |       48      |   48   |   0    |  12.4s   |
+----------------+------------+---------------+--------+--------+----------+
| TOTAL          |    32      |      421      |  421   |   0    | 107.8s   |
+----------------+------------+---------------+--------+--------+----------+
```

---

## 3. Detailed Test Module Breakdown

### 3.1 Accounts Application (114 Tests — 100% Pass)
*Primary Owner: Uttam (PES1UG24CS697)*

| Test File | Test Suite Class | Tests | Scope & Verified Capabilities |
| :--- | :--- | :---: | :--- |
| `accounts/tests.py` | `UserModelTests` | 14 | Custom user model supporting 4 roles (`DONOR`, `HOSPITAL`, `STAFF`, `ADMIN`), DOB/age calculation, age $\ge 18$ validation, unique email, role property flags. |
| | `RBACServerSideEnforcementTests` | 16 | Server-side RBAC guards (`@role_required`, `@permission_required_custom`, `RoleRequiredMixin`), custom 403 Forbidden page, JSON 403 API responses. |
| | `RegistrationWorkflowTests` | 10 | Adult donor registration, under-age rejection, hospital registration creating unapproved accounts (`is_approved=False`). |
| | `AuthenticationAndSessionTests` | 8 | Dual authentication backend (`EmailOrUsernameModelBackend`), email or username login, inactive/unapproved account rejection. |
| | `ProfileAndAdminManagementTests`| 4 | Self-service profile updates, Django Admin hospital approval, user deactivation and reactivation. |
| `accounts/test_login.py` | `LoginViewTests` | 10 | Role-directed dashboard redirections, invalid credentials handling, deactivated user rejection. |
| `accounts/test_registration.py`| `RegistrationFormTests` | 12 | Duplicate email rejection (case-insensitive), password confirmation checks, form sanitization. |
| `accounts/test_sessions.py` | `SessionSecurityTests` | 10 | Session cookie flags (`HttpOnly`, `SameSite=Lax`), 30-minute inactivity expiration (`SESSION_COOKIE_AGE=1800`), explicit logout session flush. |
| `accounts/test_lockout_and_rate_limit.py` | `AccountLockoutAndRateLimitTests` | 14 | 15-minute account lockout after 5 consecutive failed attempts, sliding-window IP rate limiting (10 req/min, HTTP 429), canonical alias normalization (`user:<pk>`), trusted reverse proxy header validation (`BBMS_TRUSTED_PROXIES`). |
| `accounts/test_password_reset.py` | `PasswordResetTests` | 11 | Single-use 15-minute token generation (`PASSWORD_RESET_TIMEOUT=900`), HMAC password hash replay protection, enumeration-proof responses for unknown emails, lockout clearance upon successful reset. |
| `accounts/test_security_audit.py` | `SecurityAuditTests` | 4 | Security event auditing on failed logins, lockouts, rate limit violations, and password resets without logging plaintext credentials. |
| `accounts/test_smtp_delivery.py` | `SMTPDeliveryTests` | 1 | Live RFC 5321/5322 SMTP email delivery over local TCP loopback socket verifying end-to-end socket transport. |

---

### 3.2 Appointments Application (28 Tests — 100% Pass)
*Primary Owner: Navaneeth Tanuboddi (PES1UG24CS709)*

| Test File | Test Suite Class | Tests | Scope & Verified Capabilities |
| :--- | :--- | :---: | :--- |
| `appointments/tests.py` | `AppointmentModelTests` | 8 | Slot generation, date/time boundaries, center assignment, capacity limits. |
| | `AppointmentBookingTests` | 10 | Slot capacity auto-decrement on booking, pre-donation medical screening requirement, double-booking prevention. |
| | `AppointmentReschedulingTests` | 6 | 24-hour rescheduling cutoff boundary enforcement (allowed at $\ge 24$h, blocked inside 24h). |
| | `AppointmentCancellationTests` | 4 | Appointment cancellation, instantaneous slot capacity restoration, notification generation. |

---

### 3.3 Donors Application (32 Tests — 100% Pass)
*Primary Owner: Navaneeth Tanuboddi (PES1UG24CS709)*

| Test File | Test Suite Class | Tests | Scope & Verified Capabilities |
| :--- | :--- | :---: | :--- |
| `donors/tests.py` | `EligibilityQuestionnaireTests` | 16 | 7 medical eligibility questions, pass/fail evaluation, temporary deferral assignment, outcome audit logging. |
| `donors/test_history_rules.py` | `DonationHistoryRulesTests` | 8 | 90-day minimum donation cooldown interval, next eligible donation date calculation, donation history rendering. |
| `donors/test_profile_views.py` | `DonorProfileViewTests` | 4 | Donor dashboard rendering, upcoming appointment display, recent donation summary. |
| `donors/test_profile_api.py` | `DonorProfileAPITests` | 4 | REST API `/api/donors/profile/`, JSON serialization, authentication and permission guards. |

---

### 3.4 Inventory Application (112 Tests — 100% Pass)
*Primary Owners: Navaneeth Tanuboddi (PES1UG24CS709), Akshay Arcot (PES1UG24CS705), Uttam (PES1UG24CS697)*

| Test File | Test Suite Class | Tests | Scope & Verified Capabilities |
| :--- | :--- | :---: | :--- |
| `inventory/tests.py` | `BloodCollectionTests` | 24 | Staff-only collection recording, volume (ml), collection date/time, donor history auto-update. |
| | `BagIDUniquenessTests` | 12 | Collision-free unique Bag ID generation (`BAG-YYYYMMDD-HEX6`), duplicate Bag ID rejection. |
| | `BloodGroupManagementTests` | 14 | All 8 ABO/Rh groups, lab-confirmed blood group correction vs donor self-report isolation (`BBMS-F-023`). |
| | `BloodGroupDropdownSmokeTests` | 8 | Smoke check verifying `B+` displays as `'B+'` (not `'B-'`) across registration, profile, collection, filters, and requisition forms (Issue #43 regression). |
| | `SerologyTestingTests` | 10 | Mandatory serology panel (HIV, Hep B, Hep C, Syphilis), default Quarantined status, all Pass $\rightarrow$ Available transition, any Fail $\rightarrow$ Discarded transition. |
| `inventory/test_fefo_allocation_dispatch.py` | `FEFOAllocationDispatchTests` | 14 | First-Expiry-First-Out unit ordering (`expiry_date` ascending), allocation reservation, dispatch manifest generation (`DISP-YYYYMMDD-HEX6`). |
| `inventory/test_component_separation_and_expiry.py` | `ComponentSeparationAndExpiryTests`| 12 | Whole blood separation into RBC, Platelets, and FFP; parent unit `Separated` state; child unit Bag ID generation; component shelf lives (RBC 42d, Platelets 5d, FFP 365d); automated `expire_units` command. |
| `inventory/test_inventory_dashboard.py` | `InventoryDashboardTests` | 8 | Real-time stock matrix counts, group/component filtering, low-stock threshold visual indicators. |
| `inventory/test_quarantine_views.py` | `QuarantineViewTests` | 5 | Quarantine inventory list, elapsed quarantine days calculation, status change auditing. |
| `inventory/test_status_integrity.py` | `StatusIntegrityTests` | 3 | BloodUnit status transitions and state machine constraints. |
| `inventory/test_status_transitions.py`| `StatusTransitionRuleTests` | 2 | Finality of Discarded and Expired states. |

---

### 3.5 Requisitions Application (87 Tests — 100% Pass)
*Primary Owners: Abhinav K (PES1UG24CS701), Navaneeth Tanuboddi (PES1UG24CS709), Akshay Arcot (PES1UG24CS705)*

| Test File | Test Suite Class | Tests | Scope & Verified Capabilities |
| :--- | :--- | :---: | :--- |
| `requisitions/tests/test_views.py` | `RequisitionViewTests` | 24 | Approved hospital requisition submission, routine vs STAT requests, staff queue with STAT emergency prioritization, rejection reasons. |
| `requisitions/tests/test_services.py` | `RequisitionServiceTests` | 16 | Requisition lifecycle transitions (Submitted $\rightarrow$ Approved / Rejected / Partially Fulfilled / Fulfilled). |
| `requisitions/tests/test_cross_matching.py` | `CrossMatchingTests` | 15 | Transfusion compatibility matrix across all 8 ABO/Rh blood groups for RBC, Platelets, Plasma, and Whole Blood; blocking incompatible unit allocations; authorized clinical override workflow requiring justification logged as `CrossMatchOutcome.OVERRIDDEN`. |
| `requisitions/tests/test_fulfilment.py` | `FulfilmentTests` | 12 | Requisition quantity tracking, stock auto-decrement upon dispatch, cumulative partial and full fulfillment. |
| `requisitions/tests/test_delivery.py` | `DeliveryConfirmationTests` | 10 | Hospital delivery confirmation view and API; capturing receipt timestamp and receiving staff name; transition of unit status to `Delivered`. |
| `requisitions/tests/test_api.py` | `RequisitionAPITests` | 6 | Requisition REST API endpoints and RBAC guards. |
| `requisitions/tests/test_polling_sessions.py` | `PollingSessionTests` | 4 | Real-time polling updates and persistent staff alerts for emergency STAT requisitions. |

---

### 3.6 Core Application (48 Tests — 100% Pass)
*Primary Owners: Uttam (PES1UG24CS697), Akshay Arcot (PES1UG24CS705)*

| Test File | Test Suite Class | Tests | Scope & Verified Capabilities |
| :--- | :--- | :---: | :--- |
| `core/test_integration_donor_workflow.py` | `DonorWorkflowIntegrationTests` | 4 | Complete end-to-end donor lifecycle: registration $\rightarrow$ screening $\rightarrow$ slot booking $\rightarrow$ collection $\rightarrow$ serology clearance $\rightarrow$ Available stock $\rightarrow$ 90-day cooldown. |
| `core/test_central_audit.py` | `CentralAuditServiceTests` | 32 | Central append-only audit service, SHA-256 cryptographic hash chaining (`prev_hash`, `record_hash`), genesis block anchoring, `verify_audit_integrity` command, tamper detection, multi-layer immutability (`PermissionDenied` on mutation), admin viewer UI & API, domain deletion retention, secret scrubbing. |
| `core/test_security_deployment.py` | `SecurityDeploymentTests` | 6 | Production settings (`DEBUG=False`), mandatory secret key, HTTPS redirect, HSTS headers, Secure cookie flags, safe 500 error pages, transaction persistence. |
| `core/test_seed_data.py` | `SeedDataTests` | 3 | Idempotent `seed_data` command creating 9 role-based demo accounts, appointment slots, and blood units. |
| `core/tests.py` | `CoreViewTests` | 1 | Public homepage and availability portal without exposing PII. |
| | `RoleAwareNavbarTests` | 1 | Navigation bar rendering adapted to authenticated user role. |
| | `BloodGroupConstantsTests` | 1 | 8 ABO/Rh blood group constants, validation, compatibility helpers, and B+ label assertions. |

---

## 4. Verification Evidence & Conclusion

1. **Test Suite Integrity**: Zero regressions detected across all 421 tests.
2. **Defect Backlog Resolution**: All defects identified in Sprint 1 (DEF-001 through DEF-009) and Sprint 2 (Issue #43 dropdown label bug) have been verified as resolved.
3. **Execution Command**:
   ```bash
   .venv/bin/python manage.py test --verbosity 2
   ```
4. **Conclusion**: The unit test suite completely validates all functional modules, authorization boundaries, and state transitions, fulfilling the Unit Testing criteria of the BBMS Software Test Plan.
