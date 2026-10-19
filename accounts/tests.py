from django.test import TestCase, Client
from django.urls import reverse
from .models import User


class UserModelTests(TestCase):
    def setUp(self):
        self.donor_user = User.objects.create_user(
            username='donor1',
            email='donor1@example.com',
            password='Password123!',
            role=User.Role.DONOR,
            phone='1234567890'
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
            role=User.Role.HOSPITAL
        )

    def test_donor_role_flags(self):
        self.assertTrue(self.donor_user.is_donor)
        self.assertFalse(self.donor_user.is_staff_member)
        self.assertFalse(self.donor_user.is_administrator)
        self.assertFalse(self.donor_user.is_hospital)

    def test_staff_role_flags(self):
        self.assertFalse(self.staff_user.is_donor)
        self.assertTrue(self.staff_user.is_staff_member)
        self.assertFalse(self.staff_user.is_administrator)

    def test_admin_role_flags(self):
        self.assertFalse(self.admin_user.is_donor)
        self.assertTrue(self.admin_user.is_administrator)

    def test_hospital_role_flags(self):
        self.assertTrue(self.hospital_user.is_hospital)
        self.assertFalse(self.hospital_user.is_donor)

    def test_superuser_inherits_admin_role(self):
        superuser = User.objects.create_superuser(
            username='root',
            email='root@example.com',
            password='RootPassword123!'
        )
        self.assertEqual(superuser.role, User.Role.ADMIN)
        self.assertTrue(superuser.is_administrator)
        self.assertTrue(superuser.is_staff_member)


class AuthViewTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username='testdonor',
            email='testdonor@example.com',
            password='Password123!',
            role=User.Role.DONOR
        )

    def test_login_page_renders(self):
        response = self.client.get(reverse('accounts:login'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'accounts/login.html')

    def test_donor_login_flow(self):
        login_success = self.client.login(username='testdonor', password='Password123!')
        self.assertTrue(login_success)

        # Profile accessible when logged in
        response = self.client.get(reverse('accounts:profile'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'testdonor')

    def test_logout_flow(self):
        self.client.login(username='testdonor', password='Password123!')
        response = self.client.get(reverse('accounts:logout'), follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertFalse('_auth_user_id' in self.client.session)
