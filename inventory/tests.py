from django.test import TestCase, Client
from django.urls import reverse
from accounts.models import User


class InventoryViewTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.staff_user = User.objects.create_user(
            username='staff_inv',
            password='testpassword',
            role=User.Role.STAFF
        )

    def test_inventory_views_require_login(self):
        res = self.client.get(reverse('inventory:dashboard'))
        self.assertEqual(res.status_code, 302)

    def test_inventory_dashboard_authenticated(self):
        self.client.login(username='staff_inv', password='testpassword')
        res = self.client.get(reverse('inventory:dashboard'))
        self.assertEqual(res.status_code, 200)
        self.assertTemplateUsed(res, 'inventory/dashboard.html')
        self.assertContains(res, 'Blood Inventory Dashboard')

    def test_quarantine_authenticated(self):
        self.client.login(username='staff_inv', password='testpassword')
        res = self.client.get(reverse('inventory:quarantine'))
        self.assertEqual(res.status_code, 200)
        self.assertTemplateUsed(res, 'inventory/quarantine.html')

    def test_inventory_views_reject_unauthorized_roles(self):
        donor_user = User.objects.create_user(
            username='donor_intruder',
            password='testpassword',
            role=User.Role.DONOR
        )
        self.client.login(username=donor_user.username, password='testpassword')
        res = self.client.get(reverse('inventory:dashboard'))
        self.assertEqual(res.status_code, 403)
