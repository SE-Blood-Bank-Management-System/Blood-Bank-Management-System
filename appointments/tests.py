from django.test import TestCase, Client
from django.urls import reverse
from accounts.models import User


class AppointmentViewTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username='donor_apt',
            password='testpassword',
            role=User.Role.DONOR
        )

    def test_appointment_views_require_login(self):
        res = self.client.get(reverse('appointments:list'))
        self.assertEqual(res.status_code, 302)

    def test_appointment_views_authenticated(self):
        self.client.login(username='donor_apt', password='testpassword')
        list_res = self.client.get(reverse('appointments:list'))
        self.assertEqual(list_res.status_code, 200)
        self.assertTemplateUsed(list_res, 'appointments/list.html')

        book_res = self.client.get(reverse('appointments:book'))
        self.assertEqual(book_res.status_code, 200)
        self.assertTemplateUsed(book_res, 'appointments/book.html')
