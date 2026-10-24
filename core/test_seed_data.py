"""
Unit tests for the seed_data and seed_demo_data management commands.
Verifies demo accounts, roles, appointments, eligibility, and inventory generation.
"""
from datetime import time, timedelta
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from accounts.models import User
from appointments.models import Appointment, AppointmentSlot, BloodBankLocation
from core.constants import BloodGroup
from donors.models import MedicalEligibilityResponse
from inventory.models import BloodUnit, BloodUnitStatus, SerologyTest


class SeedDataCommandTests(TestCase):
    def test_seed_data_execution_and_model_creation(self):
        """Verifies that seed_data creates all necessary demonstration records."""
        call_command('seed_data', days=3)

        # 1. User validation
        admin_user = User.objects.get(username='admin')
        self.assertTrue(admin_user.is_superuser)
        self.assertTrue(admin_user.is_staff)
        self.assertEqual(admin_user.role, User.Role.ADMIN)
        self.assertTrue(admin_user.check_password('AdminPassword@123'))

        staff_john = User.objects.get(username='staff_john')
        self.assertEqual(staff_john.role, User.Role.STAFF)
        self.assertTrue(staff_john.check_password('StaffPassword@123'))

        donor_jane = User.objects.get(username='donor_jane')
        self.assertEqual(donor_jane.role, User.Role.DONOR)
        self.assertEqual(donor_jane.blood_group, BloodGroup.O_POS)
        self.assertTrue(donor_jane.check_password('DonorPassword@123'))

        hospital_city = User.objects.get(username='hospital_city')
        self.assertEqual(hospital_city.role, User.Role.HOSPITAL)
        self.assertTrue(hospital_city.is_approved)

        hospital_metro = User.objects.get(username='hospital_metro')
        self.assertEqual(hospital_metro.role, User.Role.HOSPITAL)
        self.assertFalse(hospital_metro.is_approved)

        # 2. Locations and slots
        self.assertGreaterEqual(BloodBankLocation.objects.count(), 3)
        self.assertTrue(AppointmentSlot.objects.filter(max_capacity=5).exists())

        # 3. Medical eligibility
        jane_elg = MedicalEligibilityResponse.objects.filter(donor=donor_jane).first()
        self.assertIsNotNone(jane_elg)
        self.assertTrue(jane_elg.is_eligible)

        vikram = User.objects.get(username='donor_vikram')
        vikram_elg = MedicalEligibilityResponse.objects.filter(donor=vikram).first()
        self.assertIsNotNone(vikram_elg)
        self.assertFalse(vikram_elg.is_eligible)

        # 4. Inventory and testing
        self.assertTrue(BloodUnit.objects.filter(status=BloodUnitStatus.QUARANTINED).exists())
        self.assertTrue(BloodUnit.objects.filter(status=BloodUnitStatus.AVAILABLE).exists())
        self.assertTrue(BloodUnit.objects.filter(status=BloodUnitStatus.DISCARDED).exists())
        self.assertGreaterEqual(SerologyTest.objects.count(), 10)

    def test_seed_data_idempotency(self):
        """Verifies that running seed_data repeatedly does not produce integrity errors."""
        call_command('seed_data', days=2)
        initial_users = User.objects.count()
        initial_units = BloodUnit.objects.count()

        call_command('seed_data', days=2)
        self.assertEqual(User.objects.count(), initial_users)
        self.assertEqual(BloodUnit.objects.count(), initial_units)

    def test_seed_demo_data_alias(self):
        """Verifies that seed_demo_data alias works equivalently."""
        call_command('seed_demo_data', days=2)
        self.assertTrue(User.objects.filter(username='admin').exists())
