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
