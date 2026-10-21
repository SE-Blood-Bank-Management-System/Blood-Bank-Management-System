import json
from datetime import date, datetime, time, timedelta
from django.core.exceptions import ValidationError
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from donors.models import MedicalEligibilityResponse
from .models import Appointment, AppointmentSlot, BloodBankLocation
from .services import (
    book_appointment_slot,
    cancel_donor_appointment,
    get_or_create_slots_for_date,
    reschedule_donor_appointment,
)


class AppointmentModelTests(TestCase):
    def setUp(self):
        self.location = BloodBankLocation.objects.create(
            name="Alpha Blood Center",
            address="100 Health Way",
            city="Metropolis"
        )
        self.donor = User.objects.create_user(
            username='donor_model_test',
            password='password123',
            role=User.Role.DONOR,
            email='donor_model@example.com'
        )
        # Give passing eligibility
        MedicalEligibilityResponse.objects.create(
            donor=self.donor,
            status=MedicalEligibilityResponse.Status.ELIGIBLE,
            responses={'feeling_well': 'yes'}
        )
        self.future_date = timezone.localdate() + timedelta(days=5)
        self.slot = AppointmentSlot.objects.create(
            location=self.location,
            date=self.future_date,
            start_time=time(10, 0),
            end_time=time(11, 0),
            max_capacity=2
        )

    def test_slot_capacity_and_availability(self):
        self.assertEqual(self.slot.booked_count, 0)
        self.assertEqual(self.slot.available_capacity, 2)
        self.assertFalse(self.slot.is_full)
        self.assertTrue(self.slot.is_available())

        # Book first appointment
        apt1 = Appointment.objects.create(
            donor=self.donor,
            slot=self.slot,
            location=self.location,
            date=self.slot.date,
            time_slot=self.slot.time_label,
            status=Appointment.Status.CONFIRMED
        )
        self.assertEqual(self.slot.booked_count, 1)
        self.assertEqual(self.slot.available_capacity, 1)
        self.assertFalse(self.slot.is_full)

        # Book second appointment
        donor2 = User.objects.create_user(username='donor2', password='pw', role=User.Role.DONOR)
        Appointment.objects.create(
            donor=donor2,
            slot=self.slot,
            location=self.location,
            date=self.slot.date,
            time_slot=self.slot.time_label,
            status=Appointment.Status.CONFIRMED
        )
        self.assertEqual(self.slot.booked_count, 2)
        self.assertEqual(self.slot.available_capacity, 0)
        self.assertTrue(self.slot.is_full)
        self.assertFalse(self.slot.is_available())

        # Cancel one appointment -> capacity releases immediately
        apt1.cancel()
        self.assertEqual(self.slot.booked_count, 1)
        self.assertEqual(self.slot.available_capacity, 1)
        self.assertFalse(self.slot.is_full)
        self.assertTrue(self.slot.is_available())

    def test_booking_reference_and_defaults(self):
        apt = Appointment.objects.create(
            donor=self.donor,
            slot=self.slot
        )
        self.assertTrue(apt.booking_reference.startswith('APT-'))
        self.assertEqual(apt.location, self.location)
        self.assertEqual(apt.date, self.slot.date)
        self.assertEqual(apt.time_slot, self.slot.time_label)

    def test_can_reschedule_boundary(self):
        # 1. Appointment in 48 hours -> can_reschedule should be True
        dt_future = timezone.now() + timedelta(hours=48)
        future_slot = AppointmentSlot.objects.create(
            location=self.location,
            date=dt_future.date(),
            start_time=dt_future.time(),
            end_time=(dt_future + timedelta(hours=1)).time(),
            max_capacity=5
        )
        apt_future = Appointment.objects.create(donor=self.donor, slot=future_slot)
        self.assertTrue(apt_future.can_reschedule())

        # 2. Appointment in 12 hours -> can_reschedule should be False (SRS BBMS-F-014, TC-APT-02)
        dt_soon = timezone.now() + timedelta(hours=12)
        soon_slot = AppointmentSlot.objects.create(
            location=self.location,
            date=dt_soon.date(),
            start_time=dt_soon.time(),
            end_time=(dt_soon + timedelta(hours=1)).time(),
            max_capacity=5
        )
        apt_soon = Appointment.objects.create(donor=self.donor, slot=soon_slot)
        self.assertFalse(apt_soon.can_reschedule())


class AppointmentCapacityAndBookingTests(TestCase):
    """
    Test Case TC-APT-01: Appointment capacity and cancellation
    SRS Requirements: BBMS-F-012, BBMS-F-013, BBMS-F-015, BBMS-F-016
    """
    def setUp(self):
        self.client = Client()
        self.location = BloodBankLocation.objects.create(
            name="Central Clinic",
            address="500 Main St",
            city="Central City"
        )
        self.eligible_donor1 = User.objects.create_user(
            username='donor_tc1',
            password='password123',
            role=User.Role.DONOR,
            email='donor_tc1@example.com'
        )
        MedicalEligibilityResponse.objects.create(
            donor=self.eligible_donor1,
            status=MedicalEligibilityResponse.Status.ELIGIBLE,
            responses={'feeling_well': 'yes'}
        )

        self.eligible_donor2 = User.objects.create_user(
            username='donor_tc2',
            password='password123',
            role=User.Role.DONOR,
            email='donor_tc2@example.com'
        )
        MedicalEligibilityResponse.objects.create(
            donor=self.eligible_donor2,
            status=MedicalEligibilityResponse.Status.ELIGIBLE,
            responses={'feeling_well': 'yes'}
        )

        self.eligible_donor3 = User.objects.create_user(
            username='donor_tc3',
            password='password123',
            role=User.Role.DONOR,
            email='donor_tc3@example.com'
        )
        MedicalEligibilityResponse.objects.create(
            donor=self.eligible_donor3,
            status=MedicalEligibilityResponse.Status.ELIGIBLE,
            responses={'feeling_well': 'yes'}
        )

        self.ineligible_donor = User.objects.create_user(
            username='donor_ineligible',
            password='password123',
            role=User.Role.DONOR,
            email='ineligible@example.com'
        )
        MedicalEligibilityResponse.objects.create(
            donor=self.ineligible_donor,
            status=MedicalEligibilityResponse.Status.INELIGIBLE,
            ineligibility_reason="Fever reported",
            responses={'feeling_well': 'no'}
        )

        self.target_date = timezone.localdate() + timedelta(days=3)
        # Create slot with max_capacity = 2
        self.slot = AppointmentSlot.objects.create(
            location=self.location,
            date=self.target_date,
            start_time=time(11, 0),
            end_time=time(12, 0),
            max_capacity=2
        )

    def test_successful_booking_and_donor_association(self):
        self.client.login(username='donor_tc1', password='password123')
        res = self.client.post(reverse('appointments:book'), {
            'location': self.location.id,
            'date': self.target_date.isoformat(),
            'slot_id': self.slot.id,
            'slot': self.slot.time_label,
            'donor_notes': 'Please arrange ground floor access'
        }, follow=True)

        self.assertEqual(res.status_code, 200)
        appointment = Appointment.objects.get(donor=self.eligible_donor1, slot=self.slot)
        self.assertEqual(appointment.status, Appointment.Status.CONFIRMED)
        self.assertEqual(appointment.location, self.location)
        self.assertEqual(appointment.donor_notes, 'Please arrange ground floor access')
        self.assertIsNotNone(appointment.eligibility_check)

    def test_ineligible_donor_booking_rejected(self):
        self.client.login(username='donor_ineligible', password='password123')
        res = self.client.post(reverse('appointments:book'), {
            'location': self.location.id,
            'date': self.target_date.isoformat(),
            'slot_id': self.slot.id,
            'slot': self.slot.time_label
        }, follow=True)

        self.assertRedirects(res, reverse('donors:eligibility'))
        self.assertFalse(Appointment.objects.filter(donor=self.ineligible_donor).exists())

    def test_overbooking_prevented_and_cancellation_releases_capacity(self):
        """
        Step 1: Fill slot to capacity (2 bookings)
        Step 2: Attempt excess booking (rejected)
        Step 3: Cancel an existing appointment
        Step 4: Retry booking (succeeds)
        """
        # Step 1: Donor 1 books
        book_appointment_slot(self.eligible_donor1, self.slot)
        # Donor 2 books
        apt2 = book_appointment_slot(self.eligible_donor2, self.slot)

        self.slot.refresh_from_db()
        self.assertEqual(self.slot.booked_count, 2)
        self.assertTrue(self.slot.is_full)

        # Step 2: Donor 3 attempts booking -> Must fail
        self.client.login(username='donor_tc3', password='password123')
        res = self.client.post(reverse('appointments:book'), {
            'location': self.location.id,
            'date': self.target_date.isoformat(),
            'slot_id': self.slot.id,
            'slot': self.slot.time_label
        }, follow=True)
        self.assertContains(res, "maximum")
        self.assertFalse(Appointment.objects.filter(donor=self.eligible_donor3).exists())

        # Step 3: Donor 2 cancels appointment
        cancel_donor_appointment(apt2, self.eligible_donor2, reason="Change of plans")
        self.slot.refresh_from_db()
        self.assertEqual(self.slot.booked_count, 1)
        self.assertFalse(self.slot.is_full)

        # Step 4: Donor 3 retries booking -> Must succeed
        res_retry = self.client.post(reverse('appointments:book'), {
            'location': self.location.id,
            'date': self.target_date.isoformat(),
            'slot_id': self.slot.id,
            'slot': self.slot.time_label
        }, follow=True)
        self.assertEqual(res_retry.status_code, 200)
        self.assertTrue(Appointment.objects.filter(donor=self.eligible_donor3).exists())


class AppointmentReschedulingBoundaryTests(TestCase):
    """
    Test Case TC-APT-02: Appointment rescheduling boundary
    SRS Requirements: BBMS-F-014
    """
    def setUp(self):
        self.client = Client()
        self.location = BloodBankLocation.objects.create(
            name="Memorial Center",
            address="200 Oak St",
            city="Metro"
        )
        self.donor = User.objects.create_user(
            username='donor_reschedule',
            password='password123',
            role=User.Role.DONOR
        )
        MedicalEligibilityResponse.objects.create(
            donor=self.donor,
            status=MedicalEligibilityResponse.Status.ELIGIBLE
        )

    def test_reschedule_allowed_outside_24_hours(self):
        # Appointment 48 hours away
        current_dt = timezone.now()
        dt_current = current_dt + timedelta(hours=48)
        old_slot = AppointmentSlot.objects.create(
            location=self.location,
            date=dt_current.date(),
            start_time=time(10, 0),
            end_time=time(11, 0),
            max_capacity=5
        )
        appointment = Appointment.objects.create(
            donor=self.donor,
            slot=old_slot
        )

        # New slot 72 hours away
        dt_new = current_dt + timedelta(hours=72)
        new_slot = AppointmentSlot.objects.create(
            location=self.location,
            date=dt_new.date(),
            start_time=time(14, 0),
            end_time=time(15, 0),
            max_capacity=5
        )

        self.client.login(username='donor_reschedule', password='password123')
        res = self.client.post(reverse('appointments:reschedule', args=[appointment.pk]), {
            'location': self.location.id,
            'date': new_slot.date.isoformat(),
            'slot_id': new_slot.id
        }, follow=True)

        self.assertEqual(res.status_code, 200)
        appointment.refresh_from_db()
        self.assertEqual(appointment.slot, new_slot)
        self.assertEqual(appointment.date, new_slot.date)

    def test_reschedule_blocked_inside_24_hours(self):
        # Appointment in 12 hours
        current_dt = timezone.now()
        dt_soon = current_dt + timedelta(hours=12)
        soon_slot = AppointmentSlot.objects.create(
            location=self.location,
            date=dt_soon.date(),
            start_time=dt_soon.time(),
            end_time=(dt_soon + timedelta(hours=1)).time(),
            max_capacity=5
        )
        appointment = Appointment.objects.create(
            donor=self.donor,
            slot=soon_slot
        )

        new_slot = AppointmentSlot.objects.create(
            location=self.location,
            date=current_dt.date() + timedelta(days=5),
            start_time=time(10, 0),
            end_time=time(11, 0),
            max_capacity=5
        )

        self.client.login(username='donor_reschedule', password='password123')
        res = self.client.post(reverse('appointments:reschedule', args=[appointment.pk]), {
            'location': self.location.id,
            'date': new_slot.date.isoformat(),
            'slot_id': new_slot.id
        }, follow=True)

        self.assertContains(res, "24 hours")
        appointment.refresh_from_db()
        self.assertEqual(appointment.slot, soon_slot)


class AppointmentSecurityAndRBACTests(TestCase):
    """
    Test access controls, permission enforcement, and cross-donor privacy.
    SRS BBMS-SR-003, Issue #9 Acceptance Criteria.
    """
    def setUp(self):
        self.client = Client()
        self.location = BloodBankLocation.objects.create(
            name="Security Test Center",
            address="1 Alpha St",
            city="Capital"
        )
        self.donor_a = User.objects.create_user(
            username='donor_alice',
            password='password123',
            role=User.Role.DONOR
        )
        MedicalEligibilityResponse.objects.create(
            donor=self.donor_a,
            status=MedicalEligibilityResponse.Status.ELIGIBLE
        )
        self.donor_b = User.objects.create_user(
            username='donor_bob',
            password='password123',
            role=User.Role.DONOR
        )
        self.staff_user = User.objects.create_user(
            username='staff_member',
            password='password123',
            role=User.Role.STAFF
        )
        self.hospital_user = User.objects.create_user(
            username='hospital_user',
            password='password123',
            role=User.Role.HOSPITAL,
            is_approved=True
        )

        self.target_date = timezone.localdate() + timedelta(days=4)
        self.slot = AppointmentSlot.objects.create(
            location=self.location,
            date=self.target_date,
            start_time=time(9, 0),
            end_time=time(10, 0),
            max_capacity=5
        )
        self.apt_a = Appointment.objects.create(
            donor=self.donor_a,
            slot=self.slot
        )

    def test_unauthenticated_access_redirects(self):
        res = self.client.get(reverse('appointments:list'))
        self.assertEqual(res.status_code, 302)

        res_detail = self.client.get(reverse('appointments:detail', args=[self.apt_a.pk]))
        self.assertEqual(res_detail.status_code, 302)

    def test_donor_cannot_view_another_donors_appointment(self):
        """
        Acceptance Criteria: Test that donors cannot view another donor's appointments.
        """
        self.client.login(username='donor_bob', password='password123')
        res = self.client.get(reverse('appointments:detail', args=[self.apt_a.pk]))
        self.assertEqual(res.status_code, 403)

    def test_donor_cannot_cancel_or_reschedule_another_donors_appointment(self):
        self.client.login(username='donor_bob', password='password123')
        res_cancel = self.client.post(reverse('appointments:cancel', args=[self.apt_a.pk]))
        self.assertEqual(res_cancel.status_code, 403)

        res_reschedule = self.client.post(reverse('appointments:reschedule', args=[self.apt_a.pk]))
        self.assertEqual(res_reschedule.status_code, 403)

    def test_staff_can_view_donor_appointment(self):
        self.client.login(username='staff_member', password='password123')
        res = self.client.get(reverse('appointments:detail', args=[self.apt_a.pk]))
        self.assertEqual(res.status_code, 200)

    def test_hospital_role_cannot_book_appointment(self):
        self.client.login(username='hospital_user', password='password123')
        res = self.client.get(reverse('appointments:book'))
        self.assertEqual(res.status_code, 403)


class AppointmentAPITests(TestCase):
    """
    SAD Section 4.3 REST API Endpoints:
    GET /api/appointments/slots/
    POST /api/appointments/
    PATCH /api/appointments/{id}
    """
    def setUp(self):
        self.client = Client()
        self.location = BloodBankLocation.objects.create(
            name="API Test Center",
            address="100 Tech Blvd",
            city="Cyber City"
        )
        self.donor = User.objects.create_user(
            username='api_donor',
            password='password123',
            role=User.Role.DONOR
        )
        MedicalEligibilityResponse.objects.create(
            donor=self.donor,
            status=MedicalEligibilityResponse.Status.ELIGIBLE
        )
        self.target_date = timezone.localdate() + timedelta(days=2)
        self.slot = AppointmentSlot.objects.create(
            location=self.location,
            date=self.target_date,
            start_time=time(10, 0),
            end_time=time(11, 0),
            max_capacity=1
        )

    def test_api_slots_endpoint(self):
        res = self.client.get(
            reverse('appointments:api_slots'),
            {'location_id': self.location.id, 'date': self.target_date.isoformat()}
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn('slots', data)
        self.assertGreaterEqual(len(data['slots']), 1)

    def test_api_post_booking_and_conflict(self):
        self.client.login(username='api_donor', password='password123')

        # First booking succeeds
        payload = {'slot_id': self.slot.id, 'notes': 'Test API booking'}
        res = self.client.post(
            reverse('appointments:api_appointments'),
            data=json.dumps(payload),
            content_type='application/json'
        )
        self.assertEqual(res.status_code, 201)
        data = res.json()
        self.assertIn('booking_reference', data['appointment'])

        # Second booking to full slot returns 409 Conflict
        donor2 = User.objects.create_user(username='api_donor2', password='pw', role=User.Role.DONOR)
        MedicalEligibilityResponse.objects.create(donor=donor2, status=MedicalEligibilityResponse.Status.ELIGIBLE)
        self.client.login(username='api_donor2', password='pw')

        res2 = self.client.post(
            reverse('appointments:api_appointments'),
            data=json.dumps(payload),
            content_type='application/json'
        )
        self.assertEqual(res2.status_code, 409)
        self.assertEqual(res2.json().get('code'), 'SLOT_FULL')

    def test_api_patch_cancel(self):
        self.client.login(username='api_donor', password='password123')
        apt = Appointment.objects.create(donor=self.donor, slot=self.slot)

        res = self.client.patch(
            reverse('appointments:api_appointment_detail', args=[apt.pk]),
            data=json.dumps({'action': 'cancel', 'reason': 'Cancelling via API'}),
            content_type='application/json'
        )
        self.assertEqual(res.status_code, 200)
        apt.refresh_from_db()
        self.assertEqual(apt.status, Appointment.Status.CANCELLED)
