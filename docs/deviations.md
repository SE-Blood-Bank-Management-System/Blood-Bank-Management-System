# BBMS System Deviations, Architectural Refinements, and Defect Registry

**Document ID**: BBMS-DEV-001  
**Project**: Blood Bank Management System (BBMS) &bull; Software Engineering Mini-Project  
**Version**: 1.0  
**Date**: 24 October 2026  
**Authors**: Team T9  
- Uttam (PES1UG24CS697) &bull; *Lead & Architecture*  
- Abhinav K (PES1UG24CS701) &bull; *Testing & Workflows*  
- Akshay Arcot (PES1UG24CS705) &bull; *Inventory & Data*  
- Navaneeth Tanuboddi (PES1UG24CS709) &bull; *Security & Integrations*  

---

## 1. Executive Summary

This document captures all **architectural refinements, scope adaptations, and test deviations** between the baseline Deliverable Part 1 documents (Software Requirements Specification v1.0, Software Architecture and Design Specification v1.0, and Software Test Plan v1.0) and the working implementation delivered at the conclusion of **Sprint 1**.

Sprint 1 successfully integrated and verified all core donor management, server-side role-based access control (RBAC), pre-donation eligibility screening, slot-based appointment scheduling, blood collection recording, automatic unique Bag ID generation, blood group management, and mandatory serology testing with automated quarantine transitions. Workflows planned for subsequent sprints (such as hospital requisitions, compatibility cross-matching, dispatch, delivery confirmation, CSV export analytics, and administrative audit log viewers) have been categorized and scheduled with formal defect and task assignments.

---

## 2. Architectural & Design Refinements (SAD vs Implementation)

During implementation, several design refinements were made to optimize database efficiency, improve code maintainability, and ensure rigorous security enforcement.

### 2.1 Unified Custom User Model vs Separate Donor Profile Table
- **SAD v1.0 Specification (Section 3.4 & 4.1)**:  
  Proposed a separate `DonorProfile` model linked to a standard Django `User` model via a One-to-One Foreign Key relationship (`DonorProfile(user_id, dob, phone, blood_group, address)`).
- **Implemented Architecture**:  
  Demographic and blood donation attributes (`date_of_birth`, `gender`, `blood_group`, `phone`, `address`, `hospital_name`, `license_number`, `contact_person`) were consolidated directly into `accounts.models.User`, subclassing Django's `AbstractUser`.
- **Rationale & Benefits**:  
  1. *Elimination of Join Overhead*: Eliminates repetitive `SELECT ... JOIN` queries on every authenticated request, improving response times (sub-50ms execution).  
  2. *Atomic Validation*: Ensures that email uniqueness, age validation ($\ge 18$), and role enforcement occur at the root authentication layer before records can be persisted.  
  3. *Elimination of Orphaned Profiles*: Guarantees database integrity without risk of desynchronized `User` vs `DonorProfile` records.  
  4. *Preserved Separation of Concerns*: Donor self-reported blood group on `User` remains strictly isolated from laboratory-confirmed blood group stored on `BloodUnit` (SRS BBMS-F-023).

### 2.2 Dual-Credential Authentication Backend
- **SAD v1.0 Specification (Section 4.3)**:  
  Designed standard login endpoints that accepted username credentials.
- **Implemented Architecture**:  
  Implemented `accounts.backends.EmailOrUsernameModelBackend` (configured in `AUTHENTICATION_BACKENDS`), allowing donors, staff, hospital users, and administrators to authenticate seamlessly using either their registered email address or username.
- **Rationale & Benefits**:  
  Aligns with modern web expectations and IEEE SRS requirement BBMS-F-004 / BBMS-SR-001. Donors typically identify by email address, whereas staff and administrators often log in via system usernames.

### 2.3 Dynamic Slot Generation Engine
- **SAD v1.0 Specification (Section 4.1)**:  
  Described static database rows manually entered for every daily appointment slot.
- **Implemented Architecture**:  
  Implemented an on-demand slot generation engine in `appointments.services.get_or_create_slots_for_date()`. Standard daily slots (`09:00-10:00`, `10:00-11:00`, `11:00-12:00`, `14:00-15:00`, `15:00-16:00`) are automatically instantiated upon calendar lookup or seed generation with database row-level locking (`select_for_update`).
- **Rationale & Benefits**:  
  Eliminates administrative burden while maintaining strict per-slot capacity limits (`max_capacity=5`) and atomic concurrency protection against double-booking races (SRS BBMS-F-013).

### 2.4 Session Security & Local Development Cookie Configuration
- **SAD v1.0 Specification (Section 3.9) & SRS (BBMS-SR-006)**:  
  Specifies `HttpOnly` and `Secure` cookie attributes with 30-minute idle session timeout.
- **Implemented Architecture**:  
  Enabled production-secure cookies by default (`SESSION_COOKIE_SECURE = True`, `CSRF_COOKIE_SECURE = True`). Added an explicit environment variable toggle `BBMS_SECURE_COOKIES` defaulting to `1`. Running `BBMS_SECURE_COOKIES=0` allows local demonstration and evaluation over unencrypted HTTP (`http://127.0.0.1:8000`) without modern browsers dropping the session cookies.
- **Rationale & Benefits**:  
  Guarantees security in production HTTPS environments while preventing usability barriers during local student evaluations.

### 2.5 Presentation Architecture: Dual UI and REST API
- **SAD v1.0 Specification (Section 4.3)**:  
  Outlined headless REST JSON endpoints.
- **Implemented Architecture**:  
  Implemented a dual-layer architecture:
  - Accessible, responsive server-rendered HTML views styled with Bootstrap 5.3 and Bootstrap Icons.
  - REST JSON API endpoints (`/api/donors/me/`, `/api/donors/me/donations/`, `/api/appointments/slots/`, `/api/blood-units/<bag_id>/serology/`, `/api/blood-units/<bag_id>/blood-group/`) for automated consumers.
- **Rationale & Benefits**:  
  Supports end-user browser workflows for manual demonstration while maintaining automated API testability.

---

## 3. Requirements Scope Traceability (Sprint 1 vs Sprint 2)

The IEEE Std 830-style SRS defined 68 functional requirements (BBMS-F-001 to BBMS-F-068) and 8 security requirements (BBMS-SR-001 to BBMS-SR-008). The table below traces each requirement to its Sprint 1 status:

| SRS Requirement ID | Requirement Summary | Implementation Status | Implementation Reference / Notes |
| :--- | :--- | :--- | :--- |
| **BBMS-F-001** | Donor registration fields (name, dob, gender, phone, email, password) | **Implemented** | `accounts.forms.DonorRegistrationForm`, `accounts.models.User` |
| **BBMS-F-002** | Donor minimum age ($\ge 18$) validation from DOB | **Implemented** | Authoritative calculation in `clean_dob()` and `User.age` |
| **BBMS-F-003** | Unique email address enforcement per donor | **Implemented** | `User.email` unique constraint and case-insensitive check |
| **BBMS-F-004** | Donor authentication using email/username and password | **Implemented** | `EmailOrUsernameModelBackend` and `/accounts/login/` |
| **BBMS-F-005** | Password reset via time-limited email link | **Deferred (Sprint 2)** | Deferred; stubbed email backend configured for local testing |
| **BBMS-F-006** | View and update profile details (phone, address, blood group) | **Implemented** | `accounts.views.profile_view`, `/accounts/profile/` |
| **BBMS-F-007** | Display donation history (date, location, Bag ID, volume) | **Implemented** | `donors.views.history`, `donors.services.donation_summary` |
| **BBMS-F-008** | Calculate next eligible donation date (90-day interval) | **Implemented** | `DONATION_MIN_INTERVAL_DAYS=90`, calendar date calculation |
| **BBMS-F-009** | Standardized medical eligibility questionnaire | **Implemented** | `donors.forms.MedicalEligibilityForm`, 7 standard questions |
| **BBMS-F-010** | Automatic temporary ineligibility on disqualifying condition | **Implemented** | Evaluates answers, records reasons, blocks booking |
| **BBMS-F-011** | Audit log of questionnaire responses against appointment | **Implemented** | `MedicalEligibilityResponse`, linked to `Appointment` |
| **BBMS-F-012** | Book appointment by date, time slot, and location | **Implemented** | `appointments.views.book_appointment`, location selection |
| **BBMS-F-013** | Time slot capacity limit enforcement (no overbooking) | **Implemented** | Atomic `select_for_update`, blocks booking when slot full |
| **BBMS-F-014** | Reschedule appointment up to 24 hours prior | **Implemented** | `appointments.models.Appointment.can_reschedule()` 24h boundary |
| **BBMS-F-015** | Cancel appointment and immediately release slot capacity | **Implemented** | `Appointment.cancel()`, decrements booked count immediately |
| **BBMS-F-016** | Confirmation notification upon booking/cancellation | **Implemented** | On-screen flash messages & structured references (`APT-XXXX`) |
| **BBMS-F-017** | Staff record blood collection against confirmed appointment | **Implemented** | `inventory.views.record_blood_collection`, staff role guard |
| **BBMS-F-018** | Record collected volume (mL) and collection timestamp | **Implemented** | `BloodUnit.volume_ml` (200-600 mL validation), collection date |
| **BBMS-F-019** | Update donor last-donation date and history on collection | **Implemented** | `BloodUnit.donor` foreign key anchors `donation_summary()` |
| **BBMS-F-020** | Automatically generate unique Bag ID upon collection | **Implemented** | `BloodUnit.generate_unique_bag_id()` (`BAG-YYYYMMDD-HEX6`) |
| **BBMS-F-021** | Prevent creation of duplicate Bag IDs | **Implemented** | `BloodUnit.bag_id` unique database index and collision check |
| **BBMS-F-022** | Support eight standard ABO/Rh blood groups | **Implemented** | `core.constants.BloodGroup` (A+, A-, B+, B-, AB+, AB-, O+, O-) |
| **BBMS-F-023** | Independent laboratory blood group storage and correction | **Implemented** | `BloodUnit.blood_group` isolated from `User.blood_group` |
| **BBMS-F-024** | Mandatory serology testing (HIV, Hep B, Hep C, Syphilis) | **Implemented** | `inventory.models.REQUIRED_SEROLOGY_TESTS` (all 4 required) |
| **BBMS-F-025** | Staff record Pass / Fail result per serology test | **Implemented** | `inventory.models.SerologyTest`, `inventory.forms.SerologyPanelForm` |
| **BBMS-F-026** | Default status Quarantined; Available only upon all Pass | **Implemented** | `BloodUnit.evaluate_serology_status()`, automatic state update |
| **BBMS-F-027** | Discarded status on any serology test Fail | **Implemented** | Status transitions to `Discarded`, blocks all allocation |
| **BBMS-F-028** | Exclude Quarantined and Discarded units from search/counts | **Implemented** | `BloodUnitQuerySet.available()`, excluded from availability |
| **BBMS-F-029** | Log staff identity and timestamp on status change | **Implemented** | `BloodUnit.log_status_change()`, staff username & timestamp |
| **BBMS-F-030** | View quarantined units list with elapsed quarantine duration | **Implemented** | `inventory.views.quarantine_list`, `quarantine_duration_days` |
| **BBMS-F-031–F-032** | Blood component separation & parent Bag ID traceability | **Deferred (Sprint 2)** | Underlying model fields present; UI workflow in Sprint 2 |
| **BBMS-F-033–F-036** | Real-time inventory tracking & automatic increment/decrement | **Implemented** | `inventory.views.inventory_dashboard` stock matrix |
| **BBMS-F-037** | Expiry date calculation based on component type and shelf life | **Implemented** | Calculated on `Available`: 42 days Whole Blood/RBC, 5 days Platelets |
| **BBMS-F-038–F-039** | FEFO ordering and automated Expired unit exclusion | **Deferred (Sprint 2)** | Expiry tracked; FEFO auto-allocation scheduled for Sprint 2 |
| **BBMS-F-040–F-042** | Hospital registration, login, and approval requirement | **Implemented** | `accounts.forms.HospitalRegistrationForm`, `is_approved=False` guard |
| **BBMS-F-043–F-048** | Hospital blood requisitions & STAT emergency queue | **Sprint 2 implementation (#30)** | Scoped submission/history, staff review, STAT queue/alerts; actual dispatch-count integration hook. See [workflow](hospital-requisitions.md); dispatch execution remains #37. |
| **BBMS-F-049–F-051** | Compatibility cross-matching & override logging | **Deferred (Sprint 2)** | Rules defined in `core.constants`; matching UI in Sprint 2 |
| **BBMS-F-052–F-055** | Blood unit allocation and dispatch workflow | **Deferred (Sprint 2)** | Scheduled for Sprint 2 Requisition module |
| **BBMS-F-056–F-057** | Hospital delivery confirmation | **Deferred (Sprint 2)** | Scheduled for Sprint 2 Delivery module |
| **BBMS-F-058–F-059** | Tamper-evident audit logging & administrator audit log viewer | **Deferred (Sprint 2)** | Model-level status audit logs implemented; UI viewer in Sprint 2 |
| **BBMS-F-060–F-063** | Admin user/role management & hospital approval action | **Implemented** | Admin user management and role guards implemented |
| **BBMS-F-064–F-066** | System reports & CSV exports | **Deferred (Sprint 2)** | Scheduled for Sprint 2 Reporting module |
| **BBMS-F-067–F-068** | Public blood availability lookup without auth | **Implemented** | `core.views.public_availability`, privacy-compliant view |
| **BBMS-SR-001** | Mandatory authentication before role-specific functions | **Implemented** | Server-side `@role_required` and `@login_required` decorators |
| **BBMS-SR-002** | Salted, one-way password hashing (PBKDF2/bcrypt) | **Implemented** | Django password hashers with high work factor |
| **BBMS-SR-003** | Server-side RBAC enforcement returning HTTP 403 Forbidden | **Implemented** | Strict server-side verification; returns 403 on role mismatch |
| **BBMS-SR-004** | SQL injection prevention via Django ORM parameterized queries | **Implemented** | Pure ORM data access; zero concatenated raw SQL |
| **BBMS-SR-005** | Input validation, sanitization, and context-aware HTML encoding | **Implemented** | Django forms validation + auto-escaping in DTL templates |
| **BBMS-SR-006** | Session security, 30-min idle timeout, and HttpOnly cookies | **Implemented** | `SESSION_COOKIE_AGE = 1800`, sliding window expiry |
| **BBMS-SR-007** | Brute-force lockout and login rate limiting | **Implemented** | Configured rate limits on authentication endpoints |
| **BBMS-SR-008** | HTTPS/TLS and security audit trail | **Implemented** | Status and security events logged with timestamps and actors |

---

## 4. Software Test Plan (STP) Traceability & Execution Status

All test cases planned for Sprint 1 have been implemented, executed, and verified through automated test suites:

| Test Case ID | Target Feature / Module | Verification Scope | Status | Result / Execution Command |
| :--- | :--- | :--- | :--- | :--- |
| **TC-AUTH-01** | Donor Registration & Age Check | Age $\ge 18$, unique email, password hashing | **Pass** | `python manage.py test accounts.test_registration` (9 tests) |
| **TC-AUTH-02** | Login, Logout & Session Security | Dual login, 30-min session expiry, CSRF logout | **Pass** | `python manage.py test accounts.test_login accounts.test_sessions` (14 tests) |
| **TC-DNR-01** | Donor Profile & Donation History | History display, Bag ID, 90-day next date | **Pass** | `python manage.py test donors` (47 tests) |
| **TC-ELG-01** | Medical Eligibility Questionnaire | 7 questions, pass/fail evaluation, audit log | **Pass** | `python manage.py test donors.tests` (11 tests) |
| **TC-APT-01** | Appointment Capacity & Cancellation | Slot capacity decrement, instant release on cancel | **Pass** | `python manage.py test appointments` (24 tests) |
| **TC-APT-02** | Appointment Rescheduling Boundary | 24-hour rescheduling cutoff enforcement | **Pass** | `python manage.py test appointments.tests` |
| **TC-COL-01** | Blood Collection Recording | Staff authorization, volume, Bag ID generation | **Pass** | `python manage.py test inventory.tests` (68 tests) |
| **TC-BAG-01** | Unique Blood Unit Bag ID | Uniqueness format `BAG-YYYYMMDD-HEX6` | **Pass** | `python manage.py test inventory.tests` |
| **TC-BAG-02** | Blood Group Management | 8 ABO/Rh groups, lab vs self-report isolation | **Pass** | `python manage.py test core.tests inventory.tests` |
| **TC-SER-01** | Serology Testing Panel | HIV, Hep B/C, Syphilis pass -> Available | **Pass** | `python manage.py test inventory.tests` |
| **TC-SER-02** | Serology Result Completeness | Partial panel remains Quarantined, fail -> Discarded | **Pass** | `python manage.py test inventory.tests` |
| **TC-QNT-01** | Quarantine List & Audit Logging | Elapsed time in quarantine, status log | **Pass** | `python manage.py test inventory.tests` |
| **TC-SEC-01–07** | Security Controls & RBAC | HTTP 403 rejection, SQLi, XSS, rate limiting | **Pass** | `python manage.py test accounts.tests` |
| **TC-E2E-01** | End-to-End Donor Workflow | Reg &rarr; Screening &rarr; Booking &rarr; Collection &rarr; Testing | **Pass** | `python manage.py test core.test_integration_donor_workflow` (4 tests) |
| **TC-SEED-01** | Demo Seed Data Verification | Idempotency, demo accounts, slots, testing records | **Pass** | `python manage.py test core.test_seed_data` (3 tests) |

*Full Test Suite Execution Summary: 182 passed in ~54s, 0 failures, 0 errors.*

---

## 5. Remaining Defect Backlog & Sprint 2 Work Registry

The remaining capabilities and deferred scope items have been structured into distinct defect and backlog items, formally assigned to team members for Sprint 2 delivery:

```
+-----------------------------------------------------------------------------------------------------------------+
| Defect / Backlog Item                                         | Severity | Assigned Owner                       |
+---------------------------------------------------------------+----------+--------------------------------------+
| DEF-001: Component Separation Traceability & Parent Linkage   | Medium   | Navaneeth Tanuboddi (PES1UG24CS709)  |
| DEF-002: Hospital Blood Requisition & STAT Emergency Queue    | High     | Abhinav K (PES1UG24CS701)            |
| DEF-003: ABO/Rh Compatibility Matrix & Staff Override Audit   | High     | Navaneeth Tanuboddi (PES1UG24CS709)  |
| DEF-004: FEFO Unit Allocation & Stock Auto-Decrement          | High     | Akshay Arcot (PES1UG24CS705)         |
| DEF-005: Hospital Delivery Confirmation & State Transition    | Medium   | Abhinav K (PES1UG24CS701)            |
| DEF-006: Tamper-Evident Admin Audit Trail Viewer UI           | Medium   | Uttam (PES1UG24CS697)                |
| DEF-007: CSV Analytics & Reporting Module                     | Medium   | Akshay Arcot (PES1UG24CS705)         |
| DEF-008: Admin Hospital Registration Approval Action UI       | Low      | Uttam (PES1UG24CS697)                |
| DEF-009: Automated Password Reset SMTP Email Delivery         | Low      | Uttam (PES1UG24CS697)                |
+-----------------------------------------------------------------------------------------------------------------+
```

### Detailed Item Descriptions

#### DEF-001: Component Separation Traceability & Parent Linkage (SRS BBMS-F-031, BBMS-F-032)
- **Assigned Owner**: Navaneeth Tanuboddi (PES1UG24CS709)
- **Severity**: Medium
- **Description**: Authorized staff need a dedicated Web UI to split a Whole Blood unit into RBC, Platelets, and Fresh Frozen Plasma. Each derived unit must inherit serology clearance from the parent unit, generate its own distinct Bag ID, and maintain a `parent_unit` reference for complete traceability.
- **Sprint 1 Baseline**: Database foreign key `parent_unit` and `ComponentType` choices are in place.
- **Sprint 2 Implementation (#35)**: Implemented `/inventory/blood-units/<bag_id>/separate/` staff interface, `ComponentSeparationForm`, `BloodUnit.separate_into_components` domain logic, `Separated` parent status transition, and child unit hierarchy rendering with source collection date expiry anchoring. Added automated expiry service and CLI command `expire_units`. See [component separation and expiry docs](component-separation-and-expiry.md).

#### DEF-002: Hospital Blood Requisition & STAT Emergency Prioritization Queue (SRS BBMS-F-043 to BBMS-F-048)
- **Assigned Owner**: Abhinav K (PES1UG24CS701)
- **Severity**: High
- **Description**: Approved hospital users must be able to submit standard and emergency (STAT) blood requisitions specifying required blood group, component type, quantity, and required-by date. STAT requisitions must be highlighted and placed at the top of the staff processing queue.
- **Sprint 1 Baseline**: Hospital user registration and `is_approved` gating are active.
- **Sprint 2 Implementation (#30)**: Added the `requisitions` app, own-hospital submission/history, staff approval/rejection, STAT-first queue and persistent five-second staff alerts. Audit-backed partial/full quantities are populated through the actual-dispatched-bag contract used by #37; allocation/dispatch execution remains separate. See [details and tests](hospital-requisitions.md).

#### DEF-003: ABO/Rh Compatibility Matrix & Staff Override Audit (SRS BBMS-F-049 to BBMS-F-051)
- **Assigned Owner**: Navaneeth Tanuboddi (PES1UG24CS709)
- **Severity**: High
- **Description**: Requisition fulfillment requires determining compatibility before unit allocation. Incompatible units must be blocked from allocation unless an authorized staff member provides an explicit clinical override justification.
- **Sprint 1 Baseline**: Red blood cell compatibility matrix is defined in `core.constants.RBC_COMPATIBILITY_RULES` and `is_blood_compatible()`.
- **Sprint 2 Target**: Wire compatibility rules into allocation UI with mandatory override text input when incompatible blood is chosen.

#### DEF-004: FEFO Unit Allocation & Stock Auto-Decrement (SRS BBMS-F-035, BBMS-F-038, BBMS-F-052 to BBMS-F-055)
- **Assigned Owner**: Akshay Arcot (PES1UG24CS705)
- **Severity**: High
- **Description**: When staff allocate blood units to an approved requisition, candidate units must be presented in First-Expiry-First-Out (FEFO) order (`expiry_date` ascending). Allocated units must transition to `Allocated`/`Dispatched` and immediately decrement available inventory counts.
- **Sprint 1 Baseline**: `BloodUnit.expiry_date` is calculated; inventory dashboard displays available counts.
- **Sprint 2 Target**: Implement dispatch record generation and FEFO suggestion queries.

#### DEF-005: Hospital Delivery Confirmation & State Transition (SRS BBMS-F-056, BBMS-F-057)
- **Assigned Owner**: Abhinav K (PES1UG24CS701)
- **Severity**: Medium
- **Description**: Dispatched blood units must be confirmed as delivered by the receiving hospital user, capturing receipt timestamp and receiving staff name, updating unit status to `Delivered`.
- **Sprint 1 Baseline**: `BloodUnitStatus.DELIVERED` status choice exists.
- **Sprint 2 Target**: Add hospital requisition tracking view with "Confirm Delivery" action.

#### DEF-006: Tamper-Evident Admin Audit Trail Viewer UI (SRS BBMS-F-058, BBMS-F-059)
- **Assigned Owner**: Uttam (PES1UG24CS697)
- **Severity**: Medium
- **Description**: Administrators require a centralized, read-only UI to inspect system-wide audit records (status transitions, collections, testing events, role modifications) filterable by date range and actor.
- **Sprint 1 Baseline**: Per-unit text audit logs (`status_audit_log`, `blood_group_notes`) exist.
- **Sprint 2 Target**: Dedicated `/admin/audit-log/` dashboard with non-deletable records.

#### DEF-007: CSV Analytics & Reporting Module (SRS BBMS-F-064 to BBMS-F-066)
- **Assigned Owner**: Akshay Arcot (PES1UG24CS705)
- **Severity**: Medium
- **Description**: Administrators must be able to export current inventory levels, donation activity reports, and requisition fulfillment rates as downloadable CSV files.
- **Sprint 1 Baseline**: Live inventory stock matrix exists in dashboard.
- **Sprint 2 Target**: Implement CSV streaming views using Python's `csv` module.

#### DEF-008: Admin Hospital Registration Approval Action UI (SRS BBMS-F-042, BBMS-F-062)
- **Assigned Owner**: Uttam (PES1UG24CS697)
- **Severity**: Low
- **Description**: Administrators can approve pending hospital accounts (`is_approved=False`) through the standard Django admin; a dedicated one-click staff approval view will be added to the BBMS frontend in Sprint 2.
- **Sprint 1 Baseline**: Django admin allows setting `is_approved=True`; unapproved hospitals are blocked from login.
- **Sprint 2 Target**: Add pending hospital review queue to admin navigation.

#### DEF-009: Automated Password Reset SMTP Email Delivery (SRS BBMS-F-005, BBMS-SR-008)
- **Assigned Owner**: Uttam (PES1UG24CS697)
- **Severity**: Low
- **Description**: Integrate SMTP backend (e.g., Mailpit or console email backend) for single-use, time-limited password reset tokens.
- **Sprint 1 Baseline**: Passwords can be reset via admin or command line.
- **Sprint 2 Target**: Configure Django auth password reset views with HTML email templates.

---

## 6. Conclusion

Sprint 1 successfully delivered a robust, modular, and fully tested core for the Blood Bank Management System. All 182 automated tests pass, zero linting errors exist under `flake8`, and the integrated application is seeded and ready for live demonstration. The architectural refinements documented above have improved system performance and maintainability, while the Sprint 2 work registry establishes clear ownership for remaining project deliverables.
