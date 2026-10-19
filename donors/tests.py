from django.test import TestCase, Client
from django.urls import reverse
from accounts.models import User


class DonorViewTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username='donor_test',
            password='testpassword',
            role=User.Role.DONOR
        )

    def test_donor_views_require_login(self):
        dashboard_res = self.client.get(reverse('donors:dashboard'))
        self.assertEqual(dashboard_res.status_code, 302)

        history_res = self.client.get(reverse('donors:history'))
        self.assertEqual(history_res.status_code, 302)

    def test_donor_views_authenticated(self):
        self.client.login(username='donor_test', password='testpassword')
        dashboard_res = self.client.get(reverse('donors:dashboard'))
        self.assertEqual(dashboard_res.status_code, 200)
        self.assertTemplateUsed(dashboard_res, 'donors/dashboard.html')

        eligibility_res = self.client.get(reverse('donors:eligibility'))
        self.assertEqual(eligibility_res.status_code, 200)
        self.assertTemplateUsed(eligibility_res, 'donors/eligibility.html')
