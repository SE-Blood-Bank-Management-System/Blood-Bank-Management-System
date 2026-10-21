from django.contrib.auth import authenticate
from django.test import TestCase
from django.urls import reverse

from .models import User


class LoginSecurityTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.password = 'SecureLogin!5328'
        cls.donor = User.objects.create_user(
            'login_donor', email='login@example.com', password=cls.password,
        )

    def setUp(self):
        self.url = reverse('accounts:login')

    def login(self, **overrides):
        return self.client.post(self.url, {
            'username': self.donor.email, 'password': self.password, **overrides,
        }, secure=True)

    def test_email_is_case_insensitive_and_username_still_works(self):
        for identifier in [' LOGIN@EXAMPLE.COM ', self.donor.username]:
            with self.subTest(identifier=identifier):
                self.client.logout()
                self.assertRedirects(self.login(username=identifier), reverse('donors:dashboard'))

    def test_invalid_credentials_and_required_fields_do_not_authenticate(self):
        for overrides in [{'password': 'wrong'}, {'username': 'unknown@example.com'},
                          {'username': ''}, {'password': ''}]:
            with self.subTest(overrides=overrides):
                response = self.login(**overrides)
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.context['form'].errors)
                self.assertNotIn('_auth_user_id', self.client.session)
                self.assertNotContains(response, self.password)

    def test_all_roles_reach_the_existing_role_destination(self):
        destinations = {
            User.Role.DONOR: 'donors:dashboard', User.Role.STAFF: 'inventory:dashboard',
            User.Role.ADMIN: 'inventory:dashboard', User.Role.HOSPITAL: 'core:home',
        }
        for role, destination in destinations.items():
            with self.subTest(role=role):
                self.client.logout()
                self.donor.role = role
                self.donor.save()
                self.assertRedirects(self.login(), reverse(destination))

    def test_unsafe_next_urls_fall_back_to_role_destination(self):
        for target in ['https://evil.example/', '//evil.example/', 'javascript:alert(1)',
                       'http://testserver/donors/dashboard/']:
            with self.subTest(target=target):
                self.client.logout()
                self.assertRedirects(self.login(next=target), reverse('donors:dashboard'))

    def test_safe_next_survives_a_failed_attempt(self):
        target = reverse('accounts:profile')
        response = self.login(password='wrong', next=target)
        self.assertContains(response, f'name="next" value="{target}"')
        self.assertContains(response, 'value="login@example.com"')
        self.assertNotContains(response, 'value="wrong"')
        self.assertRedirects(self.login(next=target), target)

    def test_inactive_and_unapproved_users_cannot_log_in(self):
        for field in ['is_active', 'is_approved']:
            with self.subTest(field=field):
                setattr(self.donor, field, False)
                self.donor.save()
                self.assertEqual(self.login().status_code, 200)
                self.assertNotIn('_auth_user_id', self.client.session)
                setattr(self.donor, field, True)

    def test_email_longer_than_username_limit_can_use_login_form(self):
        self.donor.email = 'a' * 64 + '@' + 'b' * 63 + '.' + 'c' * 30 + '.com'
        self.donor.save()
        self.assertRedirects(self.login(), reverse('donors:dashboard'))

    def test_ambiguous_identifier_is_rejected_by_all_configured_backends(self):
        User.objects.create_user(self.donor.email, email='other@example.com', password=self.password)
        self.assertIsNone(authenticate(username=self.donor.email, password=self.password))

    def test_public_visitors_cannot_access_role_protected_pages(self):
        for name in ['donors:dashboard', 'accounts:profile', 'appointments:book', 'inventory:dashboard']:
            with self.subTest(page=name):
                response = self.client.get(reverse(name), secure=True)
                self.assertEqual(response.status_code, 302)
                self.assertTrue(response.url.startswith(self.url + '?next='))
