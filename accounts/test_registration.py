from datetime import datetime, timezone
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse

from .forms import DonorRegistrationForm
from .models import User


class DonorRegistrationTests(TestCase):
    def setUp(self):
        self.url = reverse('accounts:register_donor')
        self.data = {
            'first_name': 'Jane', 'last_name': 'Doe',
            'email': 'jane@example.com', 'dob': '1995-05-15',
            'phone': '+91 9876543210', 'gender': 'Female',
            'blood_group': 'A+', 'password': 'UniqueDonation!7302',
        }

    def test_registration_creates_existing_user_profile_and_hashes_password(self):
        response = self.client.post(self.url, self.data)
        self.assertRedirects(response, reverse('donors:dashboard'))
        donor = User.objects.get(email=self.data['email'])
        self.assertEqual(donor.role, User.Role.DONOR)
        self.assertEqual(donor.get_full_name(), 'Jane Doe')
        self.assertEqual(donor.phone, self.data['phone'])
        self.assertEqual(donor.gender, 'Female')
        self.assertEqual(donor.blood_group, 'A+')
        self.assertEqual(donor.date_of_birth.isoformat(), self.data['dob'])
        self.assertTrue(donor.check_password(self.data['password']))
        self.assertNotEqual(donor.password, self.data['password'])
        self.assertEqual(int(self.client.session['_auth_user_id']), donor.pk)

    def test_birthday_boundary_and_future_dates(self):
        with patch('accounts.forms.timezone.now', return_value=datetime(2026, 10, 20, tzinfo=timezone.utc)):
            for dob, expected in [('2008-10-20', True), ('2008-10-21', False),
                                  ('2008-10-19', True), ('2027-01-01', False)]:
                with self.subTest(dob=dob):
                    form = DonorRegistrationForm({**self.data, 'dob': dob})
                    self.assertEqual(form.is_valid(), expected, form.errors)

    def test_case_insensitive_duplicate_email_rejected(self):
        User.objects.create_user('existing', email='jane@example.com', password='Password!7302')
        response = self.client.post(self.url, {**self.data, 'email': ' JANE@EXAMPLE.COM '})
        self.assertFormError(response.context['form'], 'email',
                             'An account with this email address already exists (SRS BBMS-F-003).')
        self.assertEqual(User.objects.count(), 1)

    def test_required_fields_rejected_without_creating_user(self):
        for field in ('first_name', 'last_name', 'email', 'dob', 'phone', 'gender', 'password'):
            with self.subTest(field=field):
                response = self.client.post(self.url, {**self.data, field: ''})
                self.assertIn(field, response.context['form'].errors)
                self.assertEqual(User.objects.count(), 0)

    def test_invalid_choices_and_contact_rejected(self):
        for field, value in [('email', 'invalid'), ('dob', 'invalid'), ('gender', 'invalid'),
                             ('blood_group', 'C+'), ('phone', 'not a phone')]:
            with self.subTest(field=field):
                response = self.client.post(self.url, {**self.data, field: value})
                self.assertIn(field, response.context['form'].errors)
                self.assertEqual(User.objects.count(), 0)

    def test_password_validation_uses_donor_attributes(self):
        response = self.client.post(self.url, {**self.data, 'password': 'jane@example.com'})
        self.assertIn('password', response.context['form'].errors)
        self.assertEqual(User.objects.count(), 0)

    def test_validation_preserves_values_and_shows_inline_errors_but_no_password(self):
        response = self.client.post(self.url, {**self.data, 'dob': '2015-01-01'})
        self.assertContains(response, 'value="Jane"')
        self.assertContains(response, 'value="jane@example.com"')
        self.assertContains(response, 'value="Female" selected')
        self.assertContains(response, 'id="id_dob_error"')
        self.assertNotContains(response, self.data['password'])

    def test_privileged_fields_cannot_be_submitted(self):
        self.client.post(self.url, {**self.data, 'role': 'ADMIN', 'is_staff': True, 'is_superuser': True})
        donor = User.objects.get()
        self.assertEqual(donor.role, User.Role.DONOR)
        self.assertFalse(donor.is_staff)
        self.assertFalse(donor.is_superuser)

    def test_email_can_exceed_username_length_or_match_an_existing_username(self):
        User.objects.create_user('jane@example.com', email='someone@example.com')
        for email in ['jane@example.com', 'a' * 64 + '@' + 'b' * 63 + '.' + 'c' * 30 + '.com']:
            with self.subTest(email=email):
                form = DonorRegistrationForm({**self.data, 'email': email})
                self.assertTrue(form.is_valid(), form.errors)
                donor = form.save()
                self.assertLessEqual(len(donor.username), 150)
                self.assertEqual(donor.email, email)

    def test_save_commit_false_does_not_persist(self):
        form = DonorRegistrationForm(self.data)
        self.assertTrue(form.is_valid(), form.errors)
        donor = form.save(commit=False)
        self.assertIsNone(donor.pk)
        self.assertEqual(User.objects.count(), 0)
        self.assertTrue(donor.check_password(self.data['password']))

    def test_registration_page_is_public_and_csrf_protected(self):
        self.assertEqual(self.client.get(self.url).status_code, 200)
        from django.test import Client
        self.assertEqual(Client(enforce_csrf_checks=True).post(self.url, self.data).status_code, 403)

    def test_authenticated_user_is_redirected(self):
        user = User.objects.create_user('signed-in')
        self.client.force_login(user)
        self.assertRedirects(self.client.post(self.url, self.data), reverse('core:home'))
        self.assertEqual(User.objects.count(), 1)
