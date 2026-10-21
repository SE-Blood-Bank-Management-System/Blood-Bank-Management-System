from datetime import date, timedelta
from django.contrib.admin.sites import AdminSite
from django.core.exceptions import PermissionDenied
from django.test import Client, RequestFactory, TestCase
from django.urls import reverse
from django.utils import timezone
from .admin import CustomUserAdmin
from .models import User
from .rbac import (
    PERM_DONOR_PROFILE,
    PERM_MANAGE_INVENTORY,
    PERM_MANAGE_USERS,
    PERM_SUBMIT_REQUISITION,
    role_required,
)


class UserModelTests(TestCase):
    """
    Test suite for Custom User Model supporting all BBMS roles and demographics.
    SRS: 2.3, 4.1 (BBMS-F-001 to BBMS-F-004), 4.2 (BBMS-F-006), 4.7 (BBMS-F-022),
         4.13 (BBMS-F-040), 4.20 (BBMS-F-060, BBMS-F-061), 5.1.2 (BBMS-SR-001, BBMS-SR-002).
    """
    def setUp(self):
        self.eighteen_years_ago = timezone.now().date() - timedelta(days=365.25 * 25)
        self.donor_user = User.objects.create_user(
            username='donor1',
            email='donor1@example.com',
            password='Password123!',
            role=User.Role.DONOR,
            phone='1234567890',
            date_of_birth=self.eighteen_years_ago,
            gender=User.Gender.MALE,
            blood_group=User.BloodGroup.O_POS,
            address='123 Maple Street'
        )
        self.staff_user = User.objects.create_user(
            username='staff1',
            email='staff1@example.com',
            password='Password123!',
            role=User.Role.STAFF,
            phone='0987654321'
        )
        self.admin_user = User.objects.create_user(
            username='admin1',
            email='admin1@example.com',
            password='Password123!',
            role=User.Role.ADMIN
        )
        self.hospital_user = User.objects.create_user(
            username='hospital1',
            email='hospital1@example.com',
            password='Password123!',
            role=User.Role.HOSPITAL,
            hospital_name='St. Jude Memorial Hospital',
            license_number='LIC-HOSP-2026-001',
            contact_person='Dr. Sarah Connor',
            is_approved=False
        )

    def test_donor_role_flags(self):
        self.assertTrue(self.donor_user.is_donor)
        self.assertFalse(self.donor_user.is_staff_member)
        self.assertFalse(self.donor_user.is_administrator)
        self.assertFalse(self.donor_user.is_hospital)
        self.assertEqual(self.donor_user.role, User.Role.DONOR)

    def test_staff_role_flags(self):
        self.assertFalse(self.staff_user.is_donor)
        self.assertTrue(self.staff_user.is_staff_member)
        self.assertFalse(self.staff_user.is_administrator)
        self.assertFalse(self.staff_user.is_hospital)
        self.assertEqual(self.staff_user.role, User.Role.STAFF)

    def test_admin_role_flags(self):
        self.assertFalse(self.admin_user.is_donor)
        self.assertTrue(self.admin_user.is_administrator)
        self.assertTrue(self.admin_user.is_staff_member)
        self.assertFalse(self.admin_user.is_hospital)
        self.assertEqual(self.admin_user.role, User.Role.ADMIN)

    def test_hospital_role_flags(self):
        self.assertTrue(self.hospital_user.is_hospital)
        self.assertFalse(self.hospital_user.is_donor)
        self.assertFalse(self.hospital_user.is_staff_member)
        self.assertFalse(self.hospital_user.is_administrator)
        self.assertFalse(self.hospital_user.is_approved)
        self.assertEqual(self.hospital_user.role, User.Role.HOSPITAL)

    def test_superuser_inherits_admin_role_and_staff(self):
        superuser = User.objects.create_superuser(
            username='root',
            email='root@example.com',
            password='RootPassword123!'
        )
        self.assertEqual(superuser.role, User.Role.ADMIN)
        self.assertTrue(superuser.is_administrator)
        self.assertTrue(superuser.is_staff_member)
        self.assertTrue(superuser.is_staff)
        self.assertTrue(superuser.is_approved)

    def test_has_role_helper(self):
        self.assertTrue(self.donor_user.has_role(User.Role.DONOR))
        self.assertFalse(self.donor_user.has_role(User.Role.STAFF, User.Role.ADMIN))
        self.assertTrue(self.staff_user.has_role(User.Role.STAFF))
        self.assertTrue(self.admin_user.has_role(User.Role.ADMIN))

    def test_has_perm_code_helper(self):
        self.assertTrue(self.donor_user.has_perm_code(PERM_DONOR_PROFILE))
        self.assertFalse(self.donor_user.has_perm_code(PERM_MANAGE_INVENTORY))
        self.assertTrue(self.staff_user.has_perm_code(PERM_MANAGE_INVENTORY))
        self.assertFalse(self.staff_user.has_perm_code(PERM_MANAGE_USERS))
        self.assertTrue(self.admin_user.has_perm_code(PERM_MANAGE_USERS))
        self.assertTrue(self.admin_user.has_perm_code(PERM_MANAGE_INVENTORY))
        self.assertTrue(self.hospital_user.has_perm_code(PERM_SUBMIT_REQUISITION))

    def test_age_calculation_and_eligibility(self):
        # Eligible donor (25 years old)
        self.assertEqual(self.donor_user.age, 25)
        self.assertTrue(self.donor_user.is_donor_eligible_age)

        # Ineligible donor (16 years old)
        minor_dob = timezone.now().date() - timedelta(days=365.25 * 16)
        minor_donor = User.objects.create_user(
            username='minordonor',
            email='minor@example.com',
            password='Password123!',
            date_of_birth=minor_dob
        )
        self.assertEqual(minor_donor.age, 16)
        self.assertFalse(minor_donor.is_donor_eligible_age)

        # User without dob
        user_no_dob = User.objects.create_user(
            username='nodob',
            email='nodob@example.com',
            password='Password123!'
        )
        self.assertIsNone(user_no_dob.age)
        self.assertFalse(user_no_dob.is_donor_eligible_age)

    def test_unique_email_enforcement(self):
        from django.db import IntegrityError
        with self.assertRaises(IntegrityError):
            User.objects.create_user(
                username='donor_duplicate',
                email='donor1@example.com',  # already used
                password='Password123!'
            )

    def test_email_normalization(self):
        user = User.objects.create_user(
            username='mixedcase',
            email='User.Case@Example.COM ',
            password='Password123!'
        )
        self.assertEqual(user.email, 'user.case@example.com')

    def test_password_is_hashed_and_not_plaintext(self):
        raw_password = 'MySecretPassword123!'
        user = User.objects.create_user(
            username='secureuser',
            email='secure@example.com',
            password=raw_password
        )
        self.assertNotEqual(user.password, raw_password)
        self.assertTrue(user.password.startswith('pbkdf2_') or user.password.startswith('bcrypt'))
        self.assertTrue(user.check_password(raw_password))


class RBACServerSideEnforcementTests(TestCase):
    """
    Test server-side Role-Based Access Control enforcement (SRS Section 5.1.2: BBMS-SR-003).
    Verifies authorized roles are granted 200, unauthorized roles receive HTTP 403,
    and unauthenticated requests are redirected.
    """
    def setUp(self):
        self.client = Client()
        self.donor = User.objects.create_user(
            username='donor_rbac',
            email='donor_rbac@example.com',
            password='Password123!',
            role=User.Role.DONOR
        )
        self.staff = User.objects.create_user(
            username='staff_rbac',
            email='staff_rbac@example.com',
            password='Password123!',
            role=User.Role.STAFF
        )
        self.admin = User.objects.create_user(
            username='admin_rbac',
            email='admin_rbac@example.com',
            password='Password123!',
            role=User.Role.ADMIN
        )
        self.hospital = User.objects.create_user(
            username='hospital_rbac',
            email='hospital_rbac@example.com',
            password='Password123!',
            role=User.Role.HOSPITAL,
            is_approved=True
        )
        self.unapproved_hospital = User.objects.create_user(
            username='unapproved_rbac',
            email='unapproved_rbac@example.com',
            password='Password123!',
            role=User.Role.HOSPITAL,
            is_approved=False
        )

    def test_unauthenticated_requests_redirected_to_login(self):
        endpoints = [
            reverse('donors:dashboard'),
            reverse('donors:history'),
            reverse('donors:eligibility'),
            reverse('inventory:dashboard'),
            reverse('inventory:quarantine'),
            reverse('appointments:book'),
        ]
        for url in endpoints:
            response = self.client.get(url)
            self.assertEqual(response.status_code, 302)
            self.assertIn(reverse('accounts:login'), response.url)

    def test_donor_authorized_endpoints(self):
        self.client.force_login(self.donor)
        endpoints = [
            reverse('donors:dashboard'),
            reverse('donors:history'),
            reverse('donors:eligibility'),
            reverse('appointments:book'),
            reverse('appointments:list'),
        ]
        for url in endpoints:
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)

    def test_donor_unauthorized_endpoints_rejected_with_403(self):
        self.client.force_login(self.donor)
        staff_endpoints = [
            reverse('inventory:dashboard'),
            reverse('inventory:quarantine'),
        ]
        for url in staff_endpoints:
            response = self.client.get(url)
            self.assertEqual(response.status_code, 403)

    def test_staff_authorized_endpoints(self):
        self.client.force_login(self.staff)
        staff_endpoints = [
            reverse('inventory:dashboard'),
            reverse('inventory:quarantine'),
            reverse('appointments:list'),
        ]
        for url in staff_endpoints:
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)

    def test_staff_unauthorized_endpoints_rejected_with_403(self):
        self.client.force_login(self.staff)
        donor_endpoints = [
            reverse('donors:dashboard'),
            reverse('donors:history'),
            reverse('donors:eligibility'),
            reverse('appointments:book'),
        ]
        for url in donor_endpoints:
            response = self.client.get(url)
            self.assertEqual(response.status_code, 403)

    def test_hospital_unauthorized_endpoints_rejected_with_403(self):
        self.client.force_login(self.hospital)
        endpoints = [
            reverse('donors:dashboard'),
            reverse('inventory:dashboard'),
            reverse('inventory:quarantine'),
            reverse('appointments:book'),
        ]
        for url in endpoints:
            response = self.client.get(url)
            self.assertEqual(response.status_code, 403)

    def test_admin_has_broad_access(self):
        self.client.force_login(self.admin)
        endpoints = [
            reverse('donors:dashboard'),
            reverse('inventory:dashboard'),
            reverse('inventory:quarantine'),
            reverse('appointments:book'),
            reverse('appointments:list'),
        ]
        for url in endpoints:
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)

    def test_deactivated_account_rejected_with_403(self):
        rf = RequestFactory()
        req = rf.get(reverse('donors:dashboard'))
        req.user = self.donor
        self.donor.is_active = False

        from donors.views import dashboard
        with self.assertRaises(PermissionDenied):
            dashboard(req)

    def test_unapproved_hospital_rejected_with_403(self):
        self.client.force_login(self.unapproved_hospital)
        # Even when authenticated, an unapproved hospital cannot access protected endpoints
        response = self.client.get(reverse('donors:dashboard'))
        self.assertEqual(response.status_code, 403)

    def test_api_role_check_returns_json_403(self):
        self.client.force_login(self.donor)
        response = self.client.get(
            reverse('inventory:dashboard'),
            HTTP_ACCEPT='application/json'
        )
        self.assertEqual(response.status_code, 403)
        self.assertIn('application/json', response.headers.get('content-type', ''))


class RegistrationWorkflowTests(TestCase):
    """
    Test donor and hospital registration workflows, age validation, and duplicate email prevention.
    SRS: 4.1 (BBMS-F-001, BBMS-F-002, BBMS-F-003), 4.13 (BBMS-F-040, BBMS-F-042).
    """
    def setUp(self):
        self.client = Client()

    def test_valid_donor_registration(self):
        data = {
            'first_name': 'Jane',
            'last_name': 'Doe',
            'email': 'jane.doe@example.com',
            'dob': '1995-05-15',
            'phone': '+91 9876543210',
            'gender': 'Female',
            'blood_group': 'A+',
            'password': 'SecurePassword123!',
        }
        response = self.client.post(reverse('accounts:register_donor'), data, follow=True)
        self.assertEqual(response.status_code, 200)

        # Verify donor is created and active
        donor = User.objects.filter(email='jane.doe@example.com').first()
        self.assertIsNotNone(donor)
        self.assertEqual(donor.role, User.Role.DONOR)
        self.assertTrue(donor.is_approved)
        self.assertEqual(donor.gender, 'Female')
        self.assertEqual(donor.blood_group, 'A+')
        self.assertEqual(donor.date_of_birth, date(1995, 5, 15))
        self.assertTrue(donor.is_donor_eligible_age)

    def test_donor_registration_under_18_rejected(self):
        # 16 years old
        dob_minor = (timezone.now().date() - timedelta(days=365.25 * 16)).isoformat()
        data = {
            'first_name': 'Young',
            'last_name': 'Donor',
            'email': 'young@example.com',
            'dob': dob_minor,
            'phone': '+91 9876543210',
            'gender': 'Male',
            'blood_group': 'O+',
            'password': 'SecurePassword123!',
        }
        response = self.client.post(reverse('accounts:register_donor'), data)
        self.assertEqual(response.status_code, 200)

        # Donor must NOT have been created
        self.assertFalse(User.objects.filter(email='young@example.com').exists())
        self.assertContains(response, '18 years old')

    def test_donor_registration_duplicate_email_rejected(self):
        User.objects.create_user(
            username='existing_donor',
            email='existing@example.com',
            password='Password123!'
        )
        data = {
            'first_name': 'Second',
            'last_name': 'User',
            'email': 'existing@example.com',
            'dob': '1990-01-01',
            'phone': '+91 9876543210',
            'gender': 'Male',
            'blood_group': 'B+',
            'password': 'SecurePassword123!',
        }
        response = self.client.post(reverse('accounts:register_donor'), data)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'already exists')

    def test_hospital_registration_pending_admin_approval(self):
        data = {
            'hospital_name': 'Metropolitan General Hospital',
            'license_number': 'REG-HOSP-2026-777',
            'email': 'bloodbank@metrogov.org',
            'contact_person': 'Dr. Marcus Vance',
            'phone': '+91 80 5555 1234',
            'address': '77 Boulevard Ave, Health District',
            'password': 'HospitalSecurePass123!',
        }
        response = self.client.post(reverse('accounts:register_hospital'), data, follow=True)
        self.assertEqual(response.status_code, 200)

        hospital = User.objects.filter(email='bloodbank@metrogov.org').first()
        self.assertIsNotNone(hospital)
        self.assertEqual(hospital.role, User.Role.HOSPITAL)
        # Pending admin approval (SRS BBMS-F-040, BBMS-F-042)
        self.assertFalse(hospital.is_approved)
        self.assertContains(response, 'pending administrator approval')


class AuthenticationAndSessionTests(TestCase):
    """
    Test authentication, username/email dual login, approval enforcement,
    and role-based redirects.
    SRS: 4.1 (BBMS-F-004), 4.13 (BBMS-F-041), 4.20 (BBMS-F-063), 5.1.2 (BBMS-SR-001, BBMS-SR-006).
    """
    def setUp(self):
        self.client = Client()
        self.donor = User.objects.create_user(
            username='donor_auth',
            email='donor_auth@example.com',
            password='AuthPassword123!',
            role=User.Role.DONOR,
            is_approved=True
        )
        self.staff = User.objects.create_user(
            username='staff_auth',
            email='staff_auth@example.com',
            password='AuthPassword123!',
            role=User.Role.STAFF,
            is_approved=True
        )
        self.unapproved_hospital = User.objects.create_user(
            username='hosp_pending',
            email='hosp_pending@example.com',
            password='AuthPassword123!',
            role=User.Role.HOSPITAL,
            is_approved=False
        )
        self.deactivated_user = User.objects.create_user(
            username='deactivated',
            email='deactivated@example.com',
            password='AuthPassword123!',
            role=User.Role.DONOR,
            is_active=False
        )

    def test_login_with_username_success(self):
        login_res = self.client.login(username='donor_auth', password='AuthPassword123!')
        self.assertTrue(login_res)

    def test_login_with_email_success(self):
        login_res = self.client.login(username='donor_auth@example.com', password='AuthPassword123!')
        self.assertTrue(login_res)

    def test_login_view_redirects_donor_to_dashboard(self):
        response = self.client.post(reverse('accounts:login'), {
            'username': 'donor_auth@example.com',
            'password': 'AuthPassword123!'
        })
        self.assertRedirects(response, reverse('donors:dashboard'))

    def test_login_view_redirects_staff_to_inventory(self):
        response = self.client.post(reverse('accounts:login'), {
            'username': 'staff_auth@example.com',
            'password': 'AuthPassword123!'
        })
        self.assertRedirects(response, reverse('inventory:dashboard'))

    def test_login_preserves_next_parameter(self):
        target_url = reverse('appointments:list')
        response = self.client.post(
            f"{reverse('accounts:login')}?next={target_url}",
            {
                'username': 'donor_auth@example.com',
                'password': 'AuthPassword123!',
                'next': target_url
            }
        )
        self.assertRedirects(response, target_url)

    def test_unapproved_account_login_blocked(self):
        response = self.client.post(reverse('accounts:login'), {
            'username': 'hosp_pending@example.com',
            'password': 'AuthPassword123!'
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'pending administrator approval')
        self.assertFalse('_auth_user_id' in self.client.session)

    def test_deactivated_account_login_blocked(self):
        response = self.client.post(reverse('accounts:login'), {
            'username': 'deactivated@example.com',
            'password': 'AuthPassword123!'
        })
        self.assertEqual(response.status_code, 200)
        self.assertFalse('_auth_user_id' in self.client.session)

    def test_logout_clears_session(self):
        self.client.login(username='donor_auth', password='AuthPassword123!')
        response = self.client.post(reverse('accounts:logout'), follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertFalse('_auth_user_id' in self.client.session)


class ProfileAndAdminManagementTests(TestCase):
    """
    Test user profile viewing/updating and administrator actions.
    SRS: 4.2 (BBMS-F-006), 4.20 (BBMS-F-060, BBMS-F-062, BBMS-F-063).
    """
    def setUp(self):
        self.client = Client()
        self.donor = User.objects.create_user(
            username='profile_donor',
            email='donor_prof@example.com',
            password='Password123!',
            role=User.Role.DONOR,
            phone='1112223333',
            blood_group='A+'
        )
        self.admin = User.objects.create_superuser(
            username='admin_boss',
            email='admin_boss@example.com',
            password='Password123!'
        )

    def test_profile_view_and_update(self):
        self.client.force_login(self.donor)
        get_res = self.client.get(reverse('accounts:profile'))
        self.assertEqual(get_res.status_code, 200)
        self.assertContains(get_res, 'profile_donor')

        # Update contact phone, address, and blood group (BBMS-F-006)
        post_res = self.client.post(reverse('accounts:profile'), {
            'phone': '9998887777',
            'address': '456 Elm Street',
            'blood_group': 'O+'
        }, follow=True)
        self.assertEqual(post_res.status_code, 200)

        self.donor.refresh_from_db()
        self.assertEqual(self.donor.phone, '9998887777')
        self.assertEqual(self.donor.address, '456 Elm Street')
        self.assertEqual(self.donor.blood_group, 'O+')

    def test_admin_custom_actions(self):
        from django.contrib.sessions.middleware import SessionMiddleware
        from django.contrib.messages.middleware import MessageMiddleware

        # Setup admin instance
        site = AdminSite()
        user_admin = CustomUserAdmin(User, site)
        rf = RequestFactory()
        request = rf.get('/admin/accounts/user/')
        request.user = self.admin

        # Initialize session and messages on request
        SessionMiddleware(lambda req: None).process_request(request)
        request.session.save()
        MessageMiddleware(lambda req: None).process_request(request)

        hospital = User.objects.create_user(
            username='hosp_to_approve',
            email='hosp_app@example.com',
            password='Password123!',
            role=User.Role.HOSPITAL,
            is_approved=False
        )
        qs = User.objects.filter(pk=hospital.pk)

        # Test approve action (BBMS-F-062)
        user_admin.approve_accounts(request, qs)
        hospital.refresh_from_db()
        self.assertTrue(hospital.is_approved)

        # Test deactivate action (BBMS-F-060, BBMS-F-063)
        user_admin.deactivate_accounts(request, qs)
        hospital.refresh_from_db()
        self.assertFalse(hospital.is_active)

        # Test reactivate action (BBMS-F-060)
        user_admin.reactivate_accounts(request, qs)
        hospital.refresh_from_db()
        self.assertTrue(hospital.is_active)
