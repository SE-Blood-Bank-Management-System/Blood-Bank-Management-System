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

## 4. Modular Architecture & Apps

| Django App | SRS Section Reference | Key Responsibilities |
| :--- | :--- | :--- |
| **`accounts`** | SRS 4.1, 4.13, 4.20, 5.1 | Custom `User` model, RBAC decorators & matrix (`DONOR`, `HOSPITAL`, `STAFF`, `ADMIN`), dual login backend, registration forms, profile updates, and admin actions. |
| **`donors`** | SRS 4.2, 4.3 | Donor profile, pre-donation medical eligibility questionnaire, donation history, next eligible donation date calculation. |
| **`appointments`** | SRS 4.4 | Slot booking, time slot capacity management, appointment rescheduling, and cancellation. |
| **`inventory`** | SRS 4.6–4.12 | Bag ID assignment, ABO/Rh blood groups, mandatory serology testing (HIV, Hep B/C, Syphilis), quarantine rules, component separation, FEFO inventory. |
| **`core`** | SRS 2.1, 3.1, 4.22 | Base template, role-aware navigation bar, landing page, privacy-compliant public blood availability lookup, and global UI assets. |

---

## 5. Prerequisites

- **Python**: Version 3.10 or higher
- **pip**: Standard Python package manager
- **OS**: Linux, macOS, or Windows

---

## 6. Quickstart / Run Steps

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

### Step 5: (Optional) Create an Administrator Account
```bash
python manage.py createsuperuser
```
*(Superusers automatically inherit the `ADMIN` role and approval flags).*

### Step 6: Start the development server
```bash
python manage.py runserver
```

Open your browser and navigate to:
**[http://127.0.0.1:8000/](http://127.0.0.1:8000/)**

---

## 7. Running Automated Tests & Linting

### Run automated unit and integration tests:
```bash
python manage.py test --verbosity 2
```

### Run code linting:
```bash
flake8 .
```

To run tests for a specific module:
```bash
python manage.py test accounts
python manage.py test core
python manage.py test donors
python manage.py test appointments
python manage.py test inventory
```

---

## 8. Technology Stack

- **Backend**: Python 3.10+ / Django 5.2 (SRS 2.4, NF-013)
- **Database**: SQLite (SRS 2.4, NF-014)
- **Frontend**: HTML5, CSS3, JavaScript (ES6+), Bootstrap 5.3, Bootstrap Icons (SRS 3.1, NF-008)
- **Architecture**: Modular Monolith / Layered (SRS NF-010, SAD 3.5)
