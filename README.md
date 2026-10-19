# Blood Bank Management System (BBMS)

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)
[![Django](https://img.shields.io/badge/Django-5.2-green.svg)](https://www.djangoproject.com/)
[![Database](https://img.shields.io/badge/Database-SQLite-lightgrey.svg)](https://www.sqlite.org/)
[![Status](https://img.shields.io/badge/Status-Runnable%20Skeleton-success.svg)]()

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

## 2. Modular Architecture & Apps

| Django App | SRS Section Reference | Key Responsibilities |
| :--- | :--- | :--- |
| **`accounts`** | SRS 4.1, 4.13, 4.20, 5.1 | Custom `User` model, Role-Based Access Control (`DONOR`, `HOSPITAL`, `STAFF`, `ADMIN`), login/logout, hospital approval flag. |
| **`donors`** | SRS 4.2, 4.3 | Donor profile, pre-donation medical eligibility questionnaire, donation history, next eligible donation date calculation (90-day interval). |
| **`appointments`** | SRS 4.4 | Slot booking, time slot capacity management, appointment rescheduling, and cancellation. |
| **`inventory`** | SRS 4.6–4.12 | Bag ID assignment, ABO/Rh blood groups, mandatory serology testing (HIV, Hep B/C, Syphilis), quarantine rules, component separation, FEFO inventory. |
| **`core`** | SRS 2.1, 3.1, 4.22 | Base template, role-aware navigation bar, landing page, privacy-compliant public blood availability lookup, and global UI assets. |

---

## 3. Prerequisites

- **Python**: Version 3.10 or higher (Python 3.14 supported)
- **pip**: Standard Python package manager
- **OS**: Linux, macOS, or Windows

---

## 4. Quickstart / Run Steps

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

### Step 5: (Optional) Create an Administrator / Staff Account
To test Admin and Staff views and the role-aware navbar:
```bash
python manage.py createsuperuser
```
*(Superusers automatically inherit the `ADMIN` role).*

### Step 6: Start the development server
```bash
python manage.py runserver
```

Open your browser and navigate to:
**[http://127.0.0.1:8000/](http://127.0.0.1:8000/)**

---

## 5. Role-Aware Navigation Bar

The base layout (`templates/base.html` and `templates/navbar.html`) dynamically adapts navigation options according to the authenticated user's role:

- **Guest / Unauthenticated User**:
  - Home
  - Public Blood Availability (SRS BBMS-F-067 / F-068)
  - About BBMS
  - Sign In / Register (Donor Registration & Hospital Registration)
- **Donor**:
  - Donor Dashboard (`/donors/dashboard/`)
  - Book Donation Appointment (`/appointments/book/`)
  - My Appointments (`/appointments/`)
  - Donation History (`/donors/history/`)
  - Medical Eligibility Screening (`/donors/eligibility/`)
  - Role Badge: `Donor`
- **Blood Bank Staff**:
  - Inventory Dashboard (`/inventory/`)
  - Quarantine & Serology Testing (`/inventory/quarantine/`)
  - Appointments Overview (`/appointments/`)
  - Role Badge: `Staff`
- **Administrator**:
  - Inventory Management (`/inventory/`)
  - Quarantine & Testing (`/inventory/quarantine/`)
  - Django Administration Portal (`/admin/`)
  - Role Badge: `Administrator`
- **Hospital User**:
  - Hospital Portal & Availability
  - Role Badge: `Hospital`

---

## 6. Running Automated Tests

To run the automated test suite across all modules:
```bash
python manage.py test
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

## 7. Project Directory Structure

```text
Blood-Bank-Management-System/
├── manage.py
├── requirements.txt
├── .gitignore
├── README.md
├── bbms/                     # Django Project configuration
│   ├── __init__.py
│   ├── settings.py           # Configured for SQLite, custom User, apps & static/templates
│   ├── urls.py               # Root URL configuration delegating to apps
│   ├── wsgi.py
│   └── asgi.py
├── accounts/                 # Custom User model & authentication (RBAC)
├── donors/                   # Donor profiles, history, eligibility
├── appointments/             # Slot reservation, capacity, cancellation
├── inventory/                # Blood units, testing, quarantine, FEFO
├── core/                     # Home, public availability, about
├── templates/                # Global templates & role-aware navbar
│   ├── base.html
│   ├── navbar.html
│   ├── footer.html
│   ├── accounts/
│   ├── appointments/
│   ├── core/
│   ├── donors/
│   └── inventory/
└── static/                   # Static assets (CSS, JS)
    ├── css/style.css
    └── js/main.js
```

---

## 8. Technology Stack

- **Backend**: Python 3.10+ / Django 5.2 (SRS 2.4, NF-013)
- **Database**: SQLite (SRS 2.4, NF-014)
- **Frontend**: HTML5, CSS3, JavaScript (ES6+), Bootstrap 5.3, Bootstrap Icons (SRS 3.1, NF-008)
- **Architecture**: Modular Monolith / Layered (SRS NF-010)