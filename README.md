# Blood Bank Management System (BBMS)

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)
[![Django](https://img.shields.io/badge/Django-5.2-green.svg)](https://www.djangoproject.com/)
[![Database](https://img.shields.io/badge/Database-SQLite-lightgrey.svg)](https://www.sqlite.org/)
[![CI](https://github.com/SE-Blood-Bank-Management-System/Blood-Bank-Management-System/actions/workflows/ci.yml/badge.svg)](https://github.com/SE-Blood-Bank-Management-System/Blood-Bank-Management-System/actions/workflows/ci.yml)

> **Software Engineering Mini-Project &bull; Team T9**  
> **Authors:**  
> - Uttam (PES1UG24CS697)  
> - Abhinav K (PES1UG24CS701)  
> - Akshay Arcot (PES1UG24CS705)  
> - Navaneeth Tanuboddi (PES1UG24CS709)  

---

## 1. Project Overview

The **Blood Bank Management System (BBMS)** is an end-to-end web application developed to manage blood donation, medical eligibility screening, collection, serology testing, quarantine isolation, First-Expiry-First-Out (FEFO) inventory tracking, and emergency hospital requisitions with compatibility cross-matching.

This repository provides the core project skeleton structured into modular Django applications so that team members can implement their assigned modules in parallel without merge conflicts.

---

## 2. Custom User Model & Role-Based Access Control (RBAC)

The system implements a centralized Custom User Model (`accounts.models.User`) and a server-side Role-Based Access Control (RBAC) enforcement system adhering to IEEE Std 830-style SRS requirements:

### Supported Roles
1. **Donor (`DONOR`)**:
   - Registers with full name, email, date of birth, gender, contact number, blood group, and password.
   - Requires age $\ge 18$ calculated from authoritative server date (SRS BBMS-F-002).
   - Enforces unique email per account (SRS BBMS-F-003).
   - Manages personal profile, views donation history, and schedules appointments.
2. **Hospital User (`HOSPITAL`)**:
   - Registers with hospital name, license number, address, contact person, and official email.
   - Account is created in pending status (`is_approved=False`) requiring Administrator approval prior to activation (SRS BBMS-F-040, BBMS-F-042).
   - Submits blood requisitions, emergency/STAT requests, and confirms delivery.
3. **Blood Bank Staff (`STAFF`)**:
   - Records collections and Bag IDs, records mandatory serology results (HIV, Hep B/C, Syphilis).
   - Manages quarantined blood units, component separation, and FEFO inventory.
   - Performs compatibility cross-matching, unit allocation, and dispatch.
4. **Administrator (`ADMIN`)**:
   - Manages user accounts, activates/deactivates accounts (SRS BBMS-F-060, BBMS-F-063).
   - Reviews and approves pending hospital registrations (SRS BBMS-F-062).
   - Inspects tamper-evident audit logs and exports system reports.

### Server-Side RBAC Enforcement (SRS BBMS-SR-003)
- Authorization is strictly validated on the server side using the `@role_required(*allowed_roles)` and `@permission_required_custom(perm_code)` decorators.
- Client-side navigation hiding is treated as a usability aid only; any unauthorized attempt to access a protected view is denied with an **HTTP 403 Forbidden** response and a styled access-denied template (`templates/403.html`).
- Dual-credential authentication backend (`accounts.backends.EmailOrUsernameModelBackend`) allows users to authenticate seamlessly using either their username or email address (SRS BBMS-SR-001, BBMS-F-004, BBMS-F-041).

---

## 3. Blood Group Management (SRS 4.7: BBMS-F-022, BBMS-F-023)

The system implements consistent blood group management across donors, collected blood units, testing, and inventory workflows (TC-BAG-02):

### Core Architecture & Valid Blood Groups
- **Eight Standard ABO/Rh Blood Groups**: Shared canonical definitions (`A+`, `A-`, `B+`, `B-`, `AB+`, `AB-`, `O+`, `O-`) defined in `core.constants.BloodGroup` and `VALID_BLOOD_GROUPS`.
- **Validation**: Enforced via `core.constants.validate_blood_group` across models, forms, and API endpoints. Invalid blood groups (e.g. `C+`, `XYZ`) are strictly rejected.
- **Transfusion Compatibility Rules (SRS BBMS-F-049)**: Red blood cell compatibility matrix implemented in `core.constants.RBC_COMPATIBILITY_RULES` and `is_blood_compatible()` helper.

### Independent Storage & Separation of Concerns (SRS BBMS-F-023)
- **Donor Self-Reported Blood Group**: Stored on `User.blood_group` (or donor profile) as self-reported by the donor during registration or profile editing.
- **Unit Laboratory-Confirmed Blood Group**: Stored independently on `BloodUnit.blood_group` for collected blood units.
- **Isolation Guarantee**: Modifying or correcting a blood unit's laboratory blood group does **not** alter the donor's self-reported profile value, and vice versa.

### Recording & Correction Workflows
- **Authorized Staff Controls**: Only users with the `STAFF` or `ADMIN` role can record or correct a blood unit's blood group. Unauthorized users (donors, hospitals) are rejected with HTTP 403 Forbidden.
- **Audit Logging**: Every blood group update records the responsible staff member (`lab_confirmed_by`), timestamp (`lab_confirmed_at`), and correction rationale (`blood_group_notes`).
- **Web UI & REST API Endpoints**:
  - Staff Web View: `GET/POST /inventory/blood-units/<bag_id>/blood-group/`
  - REST API: `PATCH/POST /api/blood-units/<bag_id>/blood-group/` (accepts JSON `{"blood_group": "A+", "notes": "..."}`)

---

## 4. Donation Appointment Booking & Capacity Management (SRS 4.4: BBMS-F-012 to BBMS-F-016)

The system implements slot-based blood donation appointment scheduling, strict capacity enforcement, and lifecycle management (TC-APT-01, TC-APT-02):

### Slot Capacity & Overbooking Prevention (SRS BBMS-F-012, BBMS-F-013)
- **Time Slots & Capacity**: Configurable daily slots per donation center with maximum donor limits (`AppointmentSlot.max_capacity`, default 5).
- **Concurrency & Atomic Locking**: Bookings use atomic transactions with database row-level locking (`select_for_update`) to prevent overbooking races. Full slots reject excess bookings and return HTTP 409 Conflict via REST API.
- **Medical Eligibility Enforcement**: Only authenticated donors who have passed the pre-donation medical eligibility questionnaire (SRS BBMS-F-009) can book visits.

### Rescheduling & Cancellation Rules (SRS BBMS-F-014, BBMS-F-015)
- **24-Hour Reschedule Boundary**: Donors may reschedule up to 24 hours prior to their scheduled slot (TC-APT-02). Rescheduling inside 24 hours is rejected.
- **Immediate Capacity Release**: Cancelling an appointment automatically frees reserved slot capacity for other donors (TC-APT-01).
- **Confirmation Notifications (BBMS-F-016)**: Structured booking confirmations with unique references (`APT-XXXXXXXX`), center addresses, and screening audit records.

---

## 5. Modular Architecture & Apps

| Django App | SRS Section Reference | Key Responsibilities |
| :--- | :--- | :--- |
| **`accounts`** | SRS 4.1, 4.13, 4.20, 5.1 | Custom `User` model, RBAC decorators & matrix (`DONOR`, `HOSPITAL`, `STAFF`, `ADMIN`), dual login backend, registration forms, profile updates, and admin actions. |
| **`donors`** | SRS 4.2, 4.3 | Donor profile, pre-donation medical eligibility questionnaire, donation history, next eligible donation date calculation. |
| **`appointments`** | SRS 4.4 | Slot booking, time slot capacity management, appointment rescheduling, and cancellation. |
| **`inventory`** | SRS 4.6–4.12 | Bag ID assignment, ABO/Rh blood groups, mandatory serology testing (HIV, Hep B/C, Syphilis), quarantine rules, component separation, FEFO inventory. |
| **`core`** | SRS 2.1, 3.1, 4.22 | Base template, role-aware navigation bar, landing page, privacy-compliant public blood availability lookup, and global UI assets. |

---

## 6. Prerequisites

- **Python**: Version 3.10 or higher
- **pip**: Standard Python package manager
- **OS**: Linux, macOS, or Windows

---

## 7. Quickstart / Run Steps

A fresh clone of the repository runs with standard Django commands:

### Step 1: Clone the repository
```bash
git clone https://github.com/SE-Blood-Bank-Management-System/Blood-Bank-Management-System.git
cd Blood-Bank-Management-System
```

### Step 2: Set up a virtual environment
```bash
# Create virtual environment
python3 -m venv .venv

# Activate virtual environment
# On Linux/macOS:
source .venv/bin/activate

# On Windows (PowerShell):
# .venv\Scripts\Activate.ps1
```

### Step 3: Install dependencies
```bash
pip install -r requirements.txt
```

### Step 4: Run database migrations
The project is pre-configured with SQLite (`db.sqlite3`):
```bash
python manage.py migrate
```

### Step 5: Seed Demonstration Data
Populate the database with realistic demo accounts across all user roles, donation centers, appointment slots, medical eligibility records, and inventory units:
```bash
python manage.py seed_data
```
*(Or use the alias `python manage.py seed_demo_data`). This command is idempotent and can be safely re-run at any time.*

#### Pre-Configured Demo Accounts:
| Role | Username / Email | Password | Primary Showcase Workflow |
| :--- | :--- | :--- | :--- |
| **Administrator** | `admin` / `admin@bbms.local` | `AdminPassword@123` | System admin, user accounts, and RBAC control |
| **Blood Bank Staff** | `staff_john` / `staff.john@bbms.local` | `StaffPassword@123` | Collection recording, automatic unique Bag ID generation |
| **Lab Technician (Staff)** | `staff_mary` / `staff.mary@bbms.local` | `StaffPassword@123` | Serology test recording (HIV, Hep B/C, Syphilis), quarantine release |
| **Donor (Eligible)** | `donor_jane` / `donor.jane@bbms.local` | `DonorPassword@123` | Passed screening, active upcoming appointment booking |
| **Donor (History & Cooldown)** | `donor_rahul` / `donor.rahul@bbms.local` | `DonorPassword@123` | Multiple past donations, 90-day cooldown elapsed (eligible) |
| **Donor (Recent Cooldown)** | `donor_priya` / `donor.priya@bbms.local` | `DonorPassword@123` | Donated 30 days ago; 90-day cooldown displays 60 days remaining |
| **Donor (Ineligible)** | `donor_vikram` / `donor.vikram@bbms.local` | `DonorPassword@123` | Temporary ineligibility due to recent fever/antibiotics |
| **Hospital User (Approved)** | `hospital_city` / `hospital.city@bbms.local` | `HospitalPassword@123` | Approved hospital account (`City General Hospital`) |
| **Hospital User (Pending)** | `hospital_metro` / `hospital.metro@bbms.local` | `HospitalPassword@123` | Pending admin approval (`Metro Specialty Clinic`) |

### Step 6: (Optional) Create a Custom Administrator Account
```bash
python manage.py createsuperuser
```
*(Superusers automatically inherit the `ADMIN` role and approval flags).*

### Step 7: Start the development server

Session and CSRF cookies default to `Secure` for HTTPS. For the local HTTP demo
only, explicitly disable that flag in the terminal running the server:

```powershell
# Windows PowerShell - local HTTP development only
$env:BBMS_SECURE_COOKIES = "0"
python manage.py runserver
```

```bash
# Linux/macOS - local HTTP development only
BBMS_SECURE_COOKIES=0 python manage.py runserver
```

For HTTPS environments, leave `BBMS_SECURE_COOKIES` unset (or set it to `1`).
Sessions expire after 30 minutes without a request and renew with activity.
Logout uses a CSRF-protected POST from the navigation or profile page.
See [Issue #3 implementation and acceptance checks](docs/login-sessions.md) and
[Issue #9 Appointment Slots and Booking](docs/appointments.md).

Open your browser and navigate to:
**[http://127.0.0.1:8000/](http://127.0.0.1:8000/)**

---

## 8. Running Automated Tests & Linting

### Run automated unit and integration tests:
```bash
python manage.py test --verbosity 2
```

### Run code linting:
```bash
flake8 .
```

To run tests for a specific module or integration suite:
```bash
python manage.py test accounts
python manage.py test core
python manage.py test donors
python manage.py test appointments
python manage.py test inventory
python manage.py test core.test_integration_donor_workflow  # End-to-end donor workflow
python manage.py test core.test_seed_data                  # Demo seed data verification
```

---

## 9. Technology Stack

- **Backend**: Python 3.10+ / Django 5.2 (SRS 2.4, NF-013)
- **Database**: SQLite (SRS 2.4, NF-014)
- **Frontend**: HTML5, CSS3, JavaScript (ES6+), Bootstrap 5.3, Bootstrap Icons (SRS 3.1, NF-008)
- **Architecture**: Modular Monolith / Layered (SRS NF-010, SAD 3.5)

---

## 10. Donor Profile and History (Issue #7)

Donors can edit contact details and self-reported blood group on their profile,
view recorded donations, and see their next eligible donation date. Staff can
review donor profiles through links on blood-unit detail pages.

`DONATION_MIN_INTERVAL_DAYS` defaults to 90 in `bbms/settings.py`. Collection
history excludes derived components and future records. Medical screening is
shown separately from the donation interval.

The donor API supports `/api/donors/me`, `/api/donors/me/donations` and
`/api/donors/me/eligibility`. See [rules, access controls and API usage](docs/donor-profile-history.md).

---

## 11. Sprint Demonstration Evidence & Deviations (Issue #5)

- **Demonstration Video & Guide**: See [demo/README.md](demo/README.md) for demonstration instructions, seed account workflows, and the 60-second video storyboard.
- **System Deviations & Defect Backlog**: See [docs/deviations.md](docs/deviations.md) for detailed documentation of architectural refinements, SRS requirement traceability across sprints, and formally assigned defects for Sprint 2.

---

## 12. Blood Inventory Dashboard & Multi-Location Stock Tracking (Issue #13)

Staff and administrators can track available blood units in real-time across the eight
ABO/Rh blood groups and distinct storage locations, filter inventory by blood group,
status, location, and component, and perform sub-2-second full-text searches.

- **Available Stock Matrices**: Live counts grouped by blood group and storage location, plus component breakdown (Whole Blood, RBC, Platelets, Plasma).
- **Safety Enforcement**: Quarantined, Discarded, and Expired units are strictly excluded from available counts (`BBMS-F-028`).
- **Dynamic Updates**: Available inventory counts increment automatically upon passing serology infection testing (`BBMS-F-036`).
- **REST API Endpoint**: `GET /api/inventory/` returns JSON stock matrices, location summaries, and paginated unit search results (SAD Section 4.3).

See full architecture, endpoints, and verification in [docs/inventory-dashboard.md](docs/inventory-dashboard.md).

---

## 13. Quarantine and Status History (Issue #14)

Staff can inspect the quarantine queue and follow **Status History** from a blood
unit or queue row. History records previous/new status, actor and timestamp;
returning to quarantine starts a new elapsed-time clock.

Run `python manage.py migrate` for the new structured history table. Existing text
notes remain available. Units with status history are protected from deletion.
Programmatic status changes must use `unit.save(actor=staff_user)` rather than
queryset/bulk status updates. See [rules, retention and API endpoints](docs/quarantine-status-history.md).
