from django.test import TestCase, Client
from django.urls import reverse
from accounts.models import User


class CoreViewTests(TestCase):
    def setUp(self):
        self.client = Client()

    def test_home_page_renders_successfully(self):
        response = self.client.get(reverse('core:home'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'core/home.html')
        self.assertContains(response, 'Blood Bank Management System')

    def test_public_availability_page_renders_without_pii(self):
        response = self.client.get(reverse('core:public_availability'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'core/public_availability.html')
        self.assertContains(response, 'Public Blood Availability')
        self.assertContains(response, 'A+')
        self.assertContains(response, 'O+')

    def test_about_page_renders(self):
        response = self.client.get(reverse('core:about'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'core/about.html')
        self.assertContains(response, 'Team T9')


class RoleAwareNavbarTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.donor = User.objects.create_user(username='duser', password='pass', role=User.Role.DONOR)
        self.staff = User.objects.create_user(username='suser', password='pass', role=User.Role.STAFF)
        self.admin = User.objects.create_user(username='auser', password='pass', role=User.Role.ADMIN)

    def test_guest_navbar(self):
        response = self.client.get(reverse('core:home'))
        self.assertContains(response, 'Login')
        self.assertContains(response, 'Register')
        self.assertNotContains(response, 'Donor Dashboard')

    def test_donor_navbar(self):
        self.client.login(username='duser', password='pass')
        response = self.client.get(reverse('core:home'))
        self.assertContains(response, 'Donor Dashboard')
        self.assertContains(response, 'Book Appointment')
        self.assertContains(response, 'Donor')

    def test_staff_navbar(self):
        self.client.login(username='suser', password='pass')
        response = self.client.get(reverse('core:home'))
        self.assertContains(response, 'Quarantine & Serology')
        self.assertContains(response, 'Staff')

    def test_admin_navbar(self):
        self.client.login(username='auser', password='pass')
        response = self.client.get(reverse('core:home'))
        self.assertContains(response, 'Admin Panel')
        self.assertContains(response, 'Administrator')


class BloodGroupConstantsTests(TestCase):
    """
    Unit tests for shared ABO/Rh blood groups, validation, and compatibility rules.
    SRS: 4.7 (BBMS-F-022, BBMS-F-023), 4.16 (BBMS-F-049).
    """
    def test_eight_standard_blood_groups_defined(self):
        from core.constants import VALID_BLOOD_GROUPS, BloodGroup
        expected_groups = {'A+', 'A-', 'B+', 'B-', 'AB+', 'AB-', 'O+', 'O-'}
        self.assertEqual(set(VALID_BLOOD_GROUPS), expected_groups)
        self.assertEqual(len(VALID_BLOOD_GROUPS), 8)
        self.assertEqual(len(BloodGroup.choices), 8)

    def test_is_valid_blood_group_helper(self):
        from core.constants import VALID_BLOOD_GROUPS, is_valid_blood_group
        for bg in VALID_BLOOD_GROUPS:
            self.assertTrue(is_valid_blood_group(bg))
            self.assertTrue(is_valid_blood_group(bg.lower()))
        for invalid in ['C+', 'AB', 'O', 'xyz', '123', None, '']:
            self.assertFalse(is_valid_blood_group(invalid))

    def test_validate_blood_group_accepts_valid(self):
        from core.constants import VALID_BLOOD_GROUPS, validate_blood_group
        for bg in VALID_BLOOD_GROUPS:
            # Must not raise ValidationError
            validate_blood_group(bg)
        # Empty/None optional values should not raise
        validate_blood_group('')
        validate_blood_group(None)

    def test_validate_blood_group_rejects_invalid(self):
        from django.core.exceptions import ValidationError
        from core.constants import validate_blood_group
        for invalid in ['C+', 'INVALID', 'A++', 'O*', 'positive', 'B']:
            with self.assertRaises(ValidationError):
                validate_blood_group(invalid)

    def test_transfusion_compatibility_rules(self):
        from core.constants import (
            VALID_BLOOD_GROUPS,
            BloodGroup,
            is_blood_compatible,
            get_compatible_donor_groups,
        )
        # O- is universal RBC donor
        for recipient in VALID_BLOOD_GROUPS:
            self.assertTrue(is_blood_compatible(BloodGroup.O_NEG, recipient))
        # AB+ is universal RBC recipient
        for donor in VALID_BLOOD_GROUPS:
            self.assertTrue(is_blood_compatible(donor, BloodGroup.AB_POS))
        # Standard known incompatibilities
        self.assertFalse(is_blood_compatible(BloodGroup.A_POS, BloodGroup.O_POS))
        self.assertFalse(is_blood_compatible(BloodGroup.B_POS, BloodGroup.A_POS))
        self.assertFalse(is_blood_compatible(BloodGroup.AB_POS, BloodGroup.A_NEG))
        # Compatible donor list for A- is (O-, A-)
        self.assertEqual(
            set(get_compatible_donor_groups(BloodGroup.A_NEG)),
            {BloodGroup.O_NEG, BloodGroup.A_NEG}
        )
