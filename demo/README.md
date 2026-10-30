# Sprint 1 Demonstration Evidence & Video Guide

This directory holds the demonstration evidence, video assets, and presentation script for the
**Blood Bank Management System (BBMS) - Sprint 1 Deliverable**.

---

## 1. Demo Video Overview

https://github.com/user-attachments/assets/d119a3fc-9cf0-4850-a538-b834794d244c

- **Duration**: ~2 minutes (comprehensive end-to-end walkthrough)
- **Resolution**: 1080p (1920x1080) at 30 fps
- **Format**: MP4 (H.264 video, AAC audio)
- **System State**: Seeded via `python manage.py seed_data`
- **HTTP Session Flag**: `BBMS_SECURE_COOKIES=0` (for local HTTP demo)

---

## 2. Seed Accounts for Demonstration

The demonstration uses pre-seeded accounts configured via `python manage.py seed_data`:

| Role | Username / Login Identifier | Password | Key Workflow Showcased |
| :--- | :--- | :--- | :--- |
| **Administrator** | `admin` (`admin@bbms.local`) | `AdminPassword@123` | User and system management, RBAC enforcement |
| **Blood Bank Staff** | `staff_john` (`staff.john@bbms.local`) | `StaffPassword@123` | Recording blood collections, automatic unique Bag ID generation |
| **Lab Technician (Staff)** | `staff_mary` (`staff.mary@bbms.local`) | `StaffPassword@123` | Serology test recording (HIV, Hep B/C, Syphilis), quarantine release |
| **Donor (Eligible)** | `donor_jane` (`donor.jane@bbms.local`) | `DonorPassword@123` | Passed medical screening, active upcoming appointment booking |
| **Donor (History & Cooldown)** | `donor_rahul` (`donor.rahul@bbms.local`) | `DonorPassword@123` | Two past donations, next eligible date elapsed (eligible to donate) |
| **Donor (Recent Cooldown)** | `donor_priya` (`donor.priya@bbms.local`) | `DonorPassword@123` | Donated 30 days ago; 90-day cooldown displays 60 days remaining |
| **Donor (Ineligible)** | `donor_vikram` (`donor.vikram@bbms.local`) | `DonorPassword@123` | Temporary ineligibility due to recent fever/antibiotics |
| **Hospital User (Approved)** | `hospital_city` (`hospital.city@bbms.local`) | `HospitalPassword@123` | Approved hospital account (`City General Hospital`) |
| **Hospital User (Pending)** | `hospital_metro` (`hospital.metro@bbms.local`) | `HospitalPassword@123` | Pending admin approval (`Metro Specialty Clinic`) |

---

## 3. Second-by-Second 60-Second Demo Storyboard

The 1-minute video demonstration is structured to show the cohesive end-to-end Sprint 1 donor workflow:

```text
+-----------------------------------------------------------------------------------------+
| [00:00 - 00:10] Terminal Setup & Database Seeding                                       |
| - Terminal: `python manage.py migrate` and `python manage.py seed_data`                 |
| - Shows quick summary of 9 demo users, locations, slots, and blood units generated     |
+-----------------------------------------------------------------------------------------+
| [00:10 - 00:22] Donor Registration & Dual-Login Authentication                          |
| - Browser: Register a new donor on `/accounts/register/donor/` (Age >= 18 validation)   |
| - Or login as `donor_jane@bbms.local` / `DonorPassword@123`                             |
| - Shows role-aware navigation bar with Donor badge                                      |
+-----------------------------------------------------------------------------------------+
| [00:22 - 00:32] Medical Eligibility Screening Questionnaire                             |
| - Navigate to `/donors/eligibility/`                                                    |
| - Submits compliant answers across 7 standardized health questions                      |
| - Outcome: Instant "Eligible" badge and audit log record created                        |
+-----------------------------------------------------------------------------------------+
| [00:32 - 00:42] Appointment Slot Booking & Capacity Management                          |
| - Navigate to `/appointments/book/`                                                     |
| - Selects center ("Central Blood Bank") and available slot                             |
| - Shows capacity decrementing and unique booking reference (`APT-XXXXXXXX`)             |
+-----------------------------------------------------------------------------------------+
| [00:42 - 00:52] Staff Collection Recording & Serology Panel Quarantine Transition       |
| - Staff login as `staff_john` / `StaffPassword@123`                                     |
| - Records collection on `/inventory/collection/record/`: generates `BAG-YYYYMMDD-HEX`   |
| - Initial status: `Quarantined`                                                         |
| - Records serology panel (HIV, Hep B, Hep C, Syphilis -> all Pass)                     |
| - Automatic transition: Status moves to `Available` with 42-day FEFO shelf-life         |
+-----------------------------------------------------------------------------------------+
| [00:52 - 01:00] Donor Profile, Donation History & 90-Day Next Eligible Date             |
| - Donor views `/donors/history/` and `/donors/dashboard/`                               |
| - Displays completed collection record with Bag ID and volume                           |
| - Shows authoritative next eligible donation date calculated with 90-day interval       |
+-----------------------------------------------------------------------------------------+
```

---

## 4. How to Record the Demo Video

1. **Terminal 1: Start Server**
   ```bash
   source .venv/bin/activate
   python manage.py migrate
   python manage.py seed_data
   BBMS_SECURE_COOKIES=0 python manage.py runserver
   ```
2. **Recording Software**:
   - Use OBS Studio, SimpleScreenRecorder, or browser screen capture.
   - Record at 1920x1080 with 100% display scaling.
3. **Execution**:
   - Follow the second-by-second storyboard above.
   - Saved video file:
     [`BBMS_Demo_Sprint1.mp4`](../BBMS_Demo_Sprint1.mp4) (in repository root)
