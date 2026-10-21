# Issue #9: Appointment Slots and Booking

## Scope and Requirements

This implements GitHub Issue #9 ("Appointment slots and booking") and satisfies the SRS Section 4.4 and Test Plan (TC-APT-01, TC-APT-02) acceptance criteria.

| Requirement ID | Requirement Description | Implementation / Verification |
| --- | --- | --- |
| **BBMS-F-009 / F-012** | Pre-requisite Medical Eligibility Screening | Authenticated donors must complete and pass the Medical Eligibility Questionnaire before confirming an appointment. Ineligible donors are blocked and redirected to screening. |
| **BBMS-F-012** | Slot Selection (Date, Time, Center) | Donors select an active blood bank location, future date (up to 60 days ahead), and configured time slot. |
| **BBMS-F-013** | Slot Capacity Limit & Overbooking Prevention | Each `AppointmentSlot` has a configurable `max_capacity` (default 5). Atomic transactions with row-level locks (`select_for_update`) prevent race conditions and overbooking. Full slots return HTTP 409 Conflict in API. |
| **BBMS-F-014** | Rescheduling (24-Hour Boundary) | Donors can reschedule existing appointments up to 24 hours prior to the scheduled start time. Inside the 24-hour window, rescheduling is rejected (TC-APT-02). |
| **BBMS-F-015** | Cancellation & Capacity Release | Donors can cancel their scheduled or confirmed appointments. Reserved slot capacity is immediately released upon cancellation for other donors (TC-APT-01). |
| **BBMS-F-016** | Confirmation Notifications | On-screen success alerts and structured notification dispatch are recorded for booking, rescheduling, and cancellation events. |
| **BBMS-SR-003** | Server-Side RBAC & Cross-Donor Privacy | Unauthenticated users are redirected to login. Donors can only view and manage their own appointments (attempting to access another donor's record returns HTTP 403 Forbidden). Hospital role is denied booking access. |
| **SAD Section 4.3** | REST API Endpoints | `GET /api/appointments/slots/`, `GET /api/appointments/`, `POST /api/appointments/`, and `PATCH /api/appointments/<id>/`. |

---

## Architecture & Data Model

### 1. `BloodBankLocation`
- Represents blood donation centers and hospital wings (`name`, `address`, `city`, `contact_number`, `is_active`).
- Pre-seeded with 3 canonical blood centers (`Central City Blood Bank`, `Metro Memorial Blood Center`, `University Hospital Blood Donation Wing`).

### 2. `AppointmentSlot`
- Represents a discrete time block at a specific location on a specific date.
- Fields: `location`, `date`, `start_time`, `end_time`, `max_capacity` (default 5), `is_active`.
- Unique constraint on `(location, date, start_time)`.
- Live properties: `booked_count`, `available_capacity`, `is_full`, and `is_available()`.

### 3. `Appointment`
- Represents an individual donor booking reservation.
- Fields: `booking_reference` (auto-generated unique code `APT-XXXXXXXX`), `donor` (FK User), `slot` (FK AppointmentSlot), `location` (FK BloodBankLocation), `date`, `time_slot`, `status` (`CONFIRMED`, `SCHEDULED`, `COMPLETED`, `CANCELLED`, `RESCHEDULED`), `eligibility_check` (FK `MedicalEligibilityResponse`), `donor_notes`, `cancelled_at`, `cancellation_reason`.
- Lifecycle methods: `can_reschedule()`, `can_cancel()`, `reschedule()`, `cancel()`.

---

## User Workflows & Web UI

1. **Viewing Available Slots (`/appointments/book/`)**:
   - Donors select a center and future donation date.
   - Interactive UI fetches live slot capacities via AJAX or standard form select, displaying seats remaining badges (`X seats left` or `Full (0 left)`).
2. **Booking Confirmation (`/appointments/<id>/`)**:
   - Generates a booking slip with the unique booking reference, center address, date, time slot, donor contact info, and medical screening compliance status.
3. **Appointment Management (`/appointments/`)**:
   - Donors view all scheduled, confirmed, and past visits.
   - Action triggers allow 1-click rescheduling (if $\ge 24$ hours away) or cancellation with reason recording.
4. **Donor Dashboard Integration (`/donors/dashboard/`)**:
   - Upcoming visits are surfaced directly on the donor dashboard with direct links to details and rescheduling.

---

## Verification & Automated Test Suite

Run the full automated test suite:

```bash
# Run appointments module tests (TC-APT-01, TC-APT-02, RBAC, REST API)
python manage.py test appointments

# Run full project test suite
python manage.py test

# Verify code style and linting
flake8 .
```

All 16 test cases in `appointments` and all 134 project-wide test cases pass cleanly with 0 lint errors.
