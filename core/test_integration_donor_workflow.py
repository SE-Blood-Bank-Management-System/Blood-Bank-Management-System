"""
Integration tests for the complete Sprint 1 Donor and Blood Collection/Testing workflow.
SRS References:
- Section 4.1 (BBMS-F-001 to BBMS-F-005): Donor registration and login
- Section 4.2 (BBMS-F-006 to BBMS-F-008): Profile, history, next eligible date
- Section 4.3 (BBMS-F-009 to BBMS-F-011): Medical eligibility questionnaire
- Section 4.4 (BBMS-F-012 to BBMS-F-016): Appointment booking, reschedule, cancel
- Section 4.5 (BBMS-F-017 to BBMS-F-019): Blood collection recording
- Section 4.6 (BBMS-F-020, BBMS-F-021): Unique Bag ID generation
- Section 4.7 (BBMS-F-022, BBMS-F-023): Blood group management and independent storage
- Section 4.8 (BBMS-F-024 to BBMS-F-027): Serology testing and quarantine rules
- Section 4.9 (BBMS-F-028 to BBMS-F-030): Quarantine isolation and status audit
- Section 4.12 (BBMS-F-037): FEFO expiry calculation
- Section 5.1 (BBMS-SR-001 to BBMS-SR-006): RBAC and security
"""
from datetime import time, timedelta
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from appointments.models import Appointment, AppointmentSlot, BloodBankLocation
from core.constants import BloodGroup
from donors.models import MedicalEligibilityResponse
from inventory.models import (
    BloodUnit,
    BloodUnitStatus,
    ComponentType,
)


class Sprint1DonorWorkflowIntegrationTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.staff_client = Client()

        # Create staff user for lab / collection operations
        self.staff = User.objects.create_user(
            username='staff_test',
            email='staff@bbms.local',
            password='StaffPassword@123',
            role=User.Role.STAFF,
            is_staff=True,
            is_approved=True,
        )

        # Create donation center location
        self.location = BloodBankLocation.objects.create(
            name='Central Blood Bank',
            address='100 Feet Road, Indiranagar',
            city='Bangalore',
            state='Karnataka',
            contact_number='+91-80-2525-0001',
            contact_email='central@bbms.local',
            is_active=True,
        )

        # Create future appointment slots (well beyond 24 hours to test reschedule)
        self.slot_date_1 = timezone.localdate() + timedelta(days=3)
        self.slot_date_2 = timezone.localdate() + timedelta(days=5)

        self.slot_1 = AppointmentSlot.objects.create(
            location=self.location,
            date=self.slot_date_1,
            start_time=time(10, 0),
            end_time=time(11, 0),
            max_capacity=2,
            is_active=True,
        )

        self.slot_2 = AppointmentSlot.objects.create(
            location=self.location,
            date=self.slot_date_2,
            start_time=time(14, 0),
            end_time=time(15, 0),
            max_capacity=2,
            is_active=True,
        )

    def test_complete_donor_and_blood_lifecycle(self):
        """
        Executes and validates the end-to-end Sprint 1 workflow:
        1. Donor registration & validation (BBMS-F-001, BBMS-F-002, BBMS-F-003)
        2. Donor login & session (BBMS-F-004, BBMS-SR-001, BBMS-SR-006)
        3. Medical eligibility questionnaire completion (BBMS-F-009, BBMS-F-010, BBMS-F-011)
        4. Slot selection & appointment booking (BBMS-F-012, BBMS-F-013)
        5. Rescheduling (>24h) and capacity release on cancel (BBMS-F-014, BBMS-F-015)
        6. Staff blood collection recording with automatic Bag ID (BBMS-F-017 - BBMS-F-021)
        7. Serology testing panel & transition to Available with expiry (BBMS-F-024 - BBMS-F-027, BBMS-F-037)
        8. Donor dashboard & history reflecting 90-day next eligible date (BBMS-F-007, BBMS-F-008)
        9. Blood group independent storage & lab correction audit (BBMS-F-022, BBMS-F-023)
        10. Quarantine disposal on serology failure (BBMS-F-027, BBMS-F-028)
        """

        # ----------------------------------------------------------------------
        # 1. Donor Registration (SRS BBMS-F-001, BBMS-F-002, BBMS-F-003, BBMS-SR-001)
        # ----------------------------------------------------------------------
        registration_data = {
            'first_name': 'Jane',
            'last_name': 'Donor',
            'email': 'e2e.donor@bbms.local',
            'dob': '2000-05-15',  # Age 26 (> 18)
            'phone': '+91 9123456789',
            'gender': 'Female',
            'blood_group': 'O+',
            'password': 'UniqueDonation!7302',
        }

        reg_response = self.client.post(reverse('accounts:register_donor'), registration_data)
        self.assertRedirects(reg_response, reverse('donors:dashboard'))

        donor_user = User.objects.filter(email='e2e.donor@bbms.local').first()
        self.assertIsNotNone(donor_user)
        self.assertEqual(donor_user.role, User.Role.DONOR)
        self.assertEqual(donor_user.blood_group, BloodGroup.O_POS)
        self.assertTrue(donor_user.age >= 18)
        self.assertTrue(donor_user.check_password('UniqueDonation!7302'))

        # ----------------------------------------------------------------------
        # 2. Donor Authentication / Login Verification (SRS BBMS-F-004, BBMS-SR-001)
        # ----------------------------------------------------------------------
        # User is already logged in by registration; let's log out and verify dual-login by email
        self.client.post(reverse('accounts:logout'))
        login_res = self.client.post(
            reverse('accounts:login'),
            {'username': 'e2e.donor@bbms.local', 'password': 'UniqueDonation!7302'}
        )
        self.assertRedirects(login_res, reverse('donors:dashboard'))

        # Initial profile review: 0 past donations, next eligible date is null
        dash_initial = self.client.get(reverse('donors:dashboard'))
        self.assertEqual(dash_initial.status_code, 200)
        self.assertContains(dash_initial, 'Pending Screening')

        # ----------------------------------------------------------------------
        # 3. Medical Eligibility Screening (SRS BBMS-F-009, BBMS-F-010, BBMS-F-011)
        # ----------------------------------------------------------------------
        # Attempt booking prior to screening -> redirected to eligibility
        pre_booking_attempt = self.client.post(
            reverse('appointments:book'),
            {
                'location': self.location.id,
                'date': self.slot_date_1.isoformat(),
                'slot_id': self.slot_1.id,
            }
        )
        self.assertRedirects(pre_booking_attempt, reverse('donors:eligibility'))

        # Complete and pass questionnaire
        questionnaire_data = {
            'feeling_well': 'yes',
            'recent_fever': 'no',
            'antibiotics': 'no',
            'tattoo_piercing': 'no',
            'malaria_travel': 'no',
            'pregnancy': 'no',
            'chronic_blood_conditions': 'no',
        }
        elg_res = self.client.post(reverse('donors:eligibility'), questionnaire_data)
        self.assertEqual(elg_res.status_code, 200)

        donor_user.refresh_from_db()
        latest_elg = MedicalEligibilityResponse.objects.filter(donor=donor_user).order_by('-created_at').first()
        self.assertIsNotNone(latest_elg)
        self.assertTrue(latest_elg.is_eligible)
        self.assertEqual(latest_elg.status, MedicalEligibilityResponse.Status.ELIGIBLE)
        self.assertTrue(donor_user.is_eligible)

        # ----------------------------------------------------------------------
        # 4. Appointment Booking (SRS BBMS-F-012, BBMS-F-013)
        # ----------------------------------------------------------------------
        self.assertEqual(self.slot_1.available_capacity, 2)

        booking_data = {
            'location': self.location.id,
            'date': self.slot_date_1.isoformat(),
            'slot_id': self.slot_1.id,
            'donor_notes': 'Please use left arm for donation',
        }
        book_res = self.client.post(reverse('appointments:book'), booking_data)
        apt = Appointment.objects.filter(donor=donor_user, status=Appointment.Status.CONFIRMED).first()
        self.assertIsNotNone(apt)
        self.assertRedirects(book_res, reverse('appointments:detail', kwargs={'pk': apt.pk}))

        self.assertTrue(apt.booking_reference.startswith('APT-'))
        self.assertEqual(apt.slot, self.slot_1)
        self.assertEqual(apt.eligibility_check, latest_elg)

        # Slot capacity is decremented
        self.slot_1.refresh_from_db()
        self.assertEqual(self.slot_1.booked_count, 1)
        self.assertEqual(self.slot_1.available_capacity, 1)

        # ----------------------------------------------------------------------
        # 5. Appointment Rescheduling & Cancellation (SRS BBMS-F-014, BBMS-F-015)
        # ----------------------------------------------------------------------
        # Reschedule to slot_2 (> 24 hours away)
        reschedule_res = self.client.post(
            reverse('appointments:reschedule', kwargs={'pk': apt.id}),
            {
                'location': self.location.id,
                'date': self.slot_date_2.isoformat(),
                'slot_id': self.slot_2.id,
            }
        )
        self.assertRedirects(reschedule_res, reverse('appointments:detail', kwargs={'pk': apt.pk}))

        apt.refresh_from_db()
        self.assertEqual(apt.slot, self.slot_2)

        # Original slot capacity released
        self.slot_1.refresh_from_db()
        self.assertEqual(self.slot_1.booked_count, 0)
        self.assertEqual(self.slot_1.available_capacity, 2)

        # Cancel appointment -> immediately releases slot_2 capacity
        cancel_res = self.client.post(
            reverse('appointments:cancel', kwargs={'pk': apt.id}),
            {'reason': 'Work schedule change'}
        )
        self.assertRedirects(cancel_res, reverse('appointments:list'))

        apt.refresh_from_db()
        self.assertEqual(apt.status, Appointment.Status.CANCELLED)
        self.slot_2.refresh_from_db()
        self.assertEqual(self.slot_2.booked_count, 0)

        # Re-confirm appointment on slot_1 for collection recording
        apt.slot = self.slot_1
        apt.status = Appointment.Status.CONFIRMED
        apt.save()

        # ----------------------------------------------------------------------
        # 6. Blood Collection Recording by Staff (SRS BBMS-F-017 to BBMS-F-021)
        # ----------------------------------------------------------------------
        self.staff_client.login(username='staff_test', password='StaffPassword@123')

        collection_payload = {
            'donor': donor_user.id,
            'blood_group': BloodGroup.O_POS,
            'component_type': ComponentType.WHOLE_BLOOD,
            'volume_ml': 450,
            'location': 'Central Blood Bank',
            'collection_notes': 'Successful routine whole-blood collection',
        }
        col_res = self.staff_client.post(reverse('inventory:record_collection'), collection_payload)

        blood_unit = BloodUnit.objects.filter(donor=donor_user).order_by('-collection_date').first()
        self.assertIsNotNone(blood_unit)
        self.assertRedirects(col_res, reverse('inventory:unit_detail', kwargs={'bag_id': blood_unit.bag_id}))

        self.assertTrue(blood_unit.bag_id.startswith('BAG-'))
        self.assertEqual(blood_unit.status, BloodUnitStatus.QUARANTINED)
        self.assertEqual(blood_unit.volume_ml, 450)
        self.assertEqual(blood_unit.blood_group, BloodGroup.O_POS)
        self.assertEqual(blood_unit.collected_by, self.staff)

        # ----------------------------------------------------------------------
        # 7. Serology Infection Testing Panel (SRS BBMS-F-024 to BBMS-F-027)
        # ----------------------------------------------------------------------
        serology_payload = {
            'hiv': 'Pass',
            'hepatitis_b': 'Pass',
            'hepatitis_c': 'Pass',
            'syphilis': 'Pass',
            'notes': 'Serology panel complete and clear',
        }
        ser_res = self.staff_client.post(
            reverse('inventory:record_serology', kwargs={'bag_id': blood_unit.bag_id}),
            serology_payload
        )
        self.assertRedirects(ser_res, reverse('inventory:unit_detail', kwargs={'bag_id': blood_unit.bag_id}))

        blood_unit.refresh_from_db()
        self.assertEqual(blood_unit.status, BloodUnitStatus.AVAILABLE)
        self.assertTrue(blood_unit.has_passed_serology)
        self.assertIsNotNone(blood_unit.expiry_date)
        # Expiry is 42 days for Whole Blood (SRS BBMS-F-037)
        expected_expiry_days = (blood_unit.expiry_date.date() - blood_unit.collection_date.date()).days
        self.assertEqual(expected_expiry_days, 42)

        # ----------------------------------------------------------------------
        # 8. Donor History & Next Eligible Date (SRS BBMS-F-007, BBMS-F-008)
        # ----------------------------------------------------------------------
        dash_res = self.client.get(reverse('donors:dashboard'))
        self.assertEqual(dash_res.status_code, 200)
        self.assertContains(dash_res, blood_unit.bag_id)

        history_res = self.client.get(reverse('donors:history'))
        self.assertEqual(history_res.status_code, 200)
        self.assertContains(history_res, blood_unit.bag_id)
        self.assertContains(history_res, '450')

        # Next eligible date is 90 days after donation
        expected_next_date = timezone.localtime(blood_unit.collection_date).date() + timedelta(days=90)
        self.assertContains(history_res, expected_next_date.strftime('%d %b %Y'))

        # ----------------------------------------------------------------------
        # 9. Independent Blood Group Storage & Lab Correction (SRS BBMS-F-023)
        # ----------------------------------------------------------------------
        bg_update_res = self.staff_client.post(
            reverse('inventory:update_blood_group', kwargs={'bag_id': blood_unit.bag_id}),
            {
                'blood_group': BloodGroup.O_NEG,
                'notes': 'Subtyping confirmed Rh negative',
            }
        )
        self.assertRedirects(bg_update_res, reverse('inventory:unit_detail', kwargs={'bag_id': blood_unit.bag_id}))

        blood_unit.refresh_from_db()
        donor_user.refresh_from_db()
        self.assertEqual(blood_unit.blood_group, BloodGroup.O_NEG)
        # Donor self-reported blood group remains O+ (isolation guarantee)
        self.assertEqual(donor_user.blood_group, BloodGroup.O_POS)
        self.assertIn('Rh negative', blood_unit.blood_group_notes)

        # ----------------------------------------------------------------------
        # 10. Quarantine Disposal on Serology Failure (SRS BBMS-F-027, BBMS-F-028)
        # ----------------------------------------------------------------------
        fail_unit = BloodUnit.record_collection(
            staff_user=self.staff,
            donor=donor_user,
            blood_group=BloodGroup.O_POS,
            volume_ml=450,
            location='Central Blood Bank',
        )
        self.assertEqual(fail_unit.status, BloodUnitStatus.QUARANTINED)

        # Record failed HIV test
        fail_res = self.staff_client.post(
            reverse('inventory:record_serology', kwargs={'bag_id': fail_unit.bag_id}),
            {
                'hiv': 'Fail',
                'hepatitis_b': 'Pass',
                'hepatitis_c': 'Pass',
                'syphilis': 'Pass',
                'notes': 'Reactive on HIV assay screen',
            }
        )
        self.assertRedirects(fail_res, reverse('inventory:unit_detail', kwargs={'bag_id': fail_unit.bag_id}))

        fail_unit.refresh_from_db()
        self.assertEqual(fail_unit.status, BloodUnitStatus.DISCARDED)
        # Excluded from available inventory counts
        self.assertFalse(BloodUnit.objects.available().filter(pk=fail_unit.pk).exists())

    def test_underage_registration_rejected(self):
        """Verifies that donors under 18 years are rejected per SRS BBMS-F-002."""
        today = timezone.localdate()
        underage_dob = (today - timedelta(days=365 * 16)).isoformat()
        payload = {
            'first_name': 'Young',
            'last_name': 'Donor',
            'email': 'young.donor@bbms.local',
            'dob': underage_dob,
            'phone': '+91 9123456780',
            'gender': 'Male',
            'blood_group': 'B+',
            'password': 'StrongPassword!7302',
        }
        res = self.client.post(reverse('accounts:register_donor'), payload)
        self.assertEqual(res.status_code, 200)
        self.assertFalse(User.objects.filter(email='young.donor@bbms.local').exists())
        self.assertContains(res, 'at least 18 years old')

    def test_medical_eligibility_disqualification(self):
        """Verifies that disqualified responses set Ineligible status and block booking (SRS BBMS-F-010)."""
        donor = User.objects.create_user(
            username='donor_ill',
            email='donor.ill@bbms.local',
            password='TestPassword@123',
            role=User.Role.DONOR,
            is_approved=True,
        )
        self.client.login(username='donor.ill@bbms.local', password='TestPassword@123')

        # Submits disqualifying responses
        payload = {
            'feeling_well': 'no',
            'recent_fever': 'yes',
            'antibiotics': 'yes',
            'tattoo_piercing': 'no',
            'malaria_travel': 'no',
            'pregnancy': 'no',
            'chronic_blood_conditions': 'no',
        }
        res = self.client.post(reverse('donors:eligibility'), payload)
        self.assertEqual(res.status_code, 200)

        record = MedicalEligibilityResponse.objects.filter(donor=donor).first()
        self.assertIsNotNone(record)
        self.assertEqual(record.status, MedicalEligibilityResponse.Status.INELIGIBLE)
        self.assertFalse(record.is_eligible)
        self.assertIn('Recent fever or illness', record.ineligibility_reason)

        # Attempt to book appointment is redirected to eligibility screen
        book_res = self.client.post(
            reverse('appointments:book'),
            {
                'location': self.location.id,
                'date': self.slot_date_1.isoformat(),
                'slot_id': self.slot_1.id,
            }
        )
        self.assertRedirects(book_res, reverse('donors:eligibility'))

    def test_slot_capacity_rejection(self):
        """Verifies that booking is blocked when slot capacity is exhausted (SRS BBMS-F-013)."""
        donor1 = User.objects.create_user(
            username='donor1', email='donor1@bbms.local', password='Pass@123', role=User.Role.DONOR
        )
        donor2 = User.objects.create_user(
            username='donor2', email='donor2@bbms.local', password='Pass@123', role=User.Role.DONOR
        )
        donor3 = User.objects.create_user(
            username='donor3', email='donor3@bbms.local', password='Pass@123', role=User.Role.DONOR
        )

        # Pre-qualify donor 1, 2, and 3
        for d in (donor1, donor2, donor3):
            MedicalEligibilityResponse.objects.create(
                donor=d,
                status=MedicalEligibilityResponse.Status.ELIGIBLE,
                responses={'feeling_well': 'yes'},
            )

        # Slot 1 has capacity 2. Book 2 donors
        Appointment.objects.create(
            donor=donor1, slot=self.slot_1, location=self.location,
            date=self.slot_1.date, time_slot=self.slot_1.time_label, status=Appointment.Status.CONFIRMED
        )
        Appointment.objects.create(
            donor=donor2, slot=self.slot_1, location=self.location,
            date=self.slot_1.date, time_slot=self.slot_1.time_label, status=Appointment.Status.CONFIRMED
        )

        self.slot_1.refresh_from_db()
        self.assertTrue(self.slot_1.is_full)

        # Attempt 3rd booking by donor3
        self.client.login(username='donor3@bbms.local', password='Pass@123')
        res = self.client.post(
            reverse('appointments:book'),
            {
                'location': self.location.id,
                'date': self.slot_1.date.isoformat(),
                'slot_id': self.slot_1.id,
            }
        )
        # Should stay on page and show capacity error message
        self.assertEqual(res.status_code, 200)
        self.assertFalse(Appointment.objects.filter(donor=donor3).exists())
        self.assertEqual(self.slot_1.booked_count, 2)
