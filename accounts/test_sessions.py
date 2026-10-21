from datetime import timedelta

from django.conf import settings
from django.contrib.sessions.models import Session
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from .models import User


class SecureSessionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.password = 'SecureDonation!4826'
        cls.donor = User.objects.create_user(
            username='session_donor', email='sessions@example.com',
            password=cls.password, role=User.Role.DONOR,
        )

    def setUp(self):
        self.login_url = reverse('accounts:login')
        self.logout_url = reverse('accounts:logout')
        self.protected_url = reverse('donors:dashboard')

    def sign_in(self, client=None):
        return (client or self.client).post(self.login_url, {
            'username': self.donor.email, 'password': self.password,
        }, secure=True)

    def test_secure_cookie_has_explicit_expiry(self):
        response = self.sign_in()
        cookie = response.cookies[settings.SESSION_COOKIE_NAME]
        self.assertTrue(cookie['secure'])
        self.assertTrue(cookie['httponly'])
        self.assertEqual(cookie['samesite'], 'Lax')
        self.assertEqual(int(cookie['max-age']), 1800)
        self.assertTrue(cookie['expires'])
        self.assertTrue(settings.CSRF_COOKIE_SECURE)
        self.assertEqual(settings.SESSION_COOKIE_AGE, 1800)
        self.assertTrue(settings.SESSION_SAVE_EVERY_REQUEST)

    def test_activity_renews_server_expiry_and_cookie(self):
        self.sign_in()
        key = self.client.session.session_key
        earlier_expiry = timezone.now() + timedelta(seconds=100)
        Session.objects.filter(session_key=key).update(expire_date=earlier_expiry)
        response = self.client.get(self.protected_url, secure=True)
        self.assertEqual(response.status_code, 200)
        stored = Session.objects.get(session_key=key)
        self.assertGreater(stored.expire_date, earlier_expiry)
        self.assertAlmostEqual((stored.expire_date - timezone.now()).total_seconds(), 1800, delta=10)
        self.assertIn(settings.SESSION_COOKIE_NAME, response.cookies)

    def test_expired_session_cannot_access_protected_html_or_api(self):
        self.sign_in()
        key = self.client.session.session_key
        Session.objects.filter(session_key=key).update(expire_date=timezone.now() - timedelta(seconds=1))
        response = self.client.get(self.protected_url, secure=True)
        self.assertRedirects(response, f'{self.login_url}?next={self.protected_url}')
        response = self.client.get(self.protected_url, secure=True, HTTP_ACCEPT='application/json')
        self.assertEqual(response.status_code, 401)
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_logout_flushes_session_and_old_cookie_cannot_be_replayed(self):
        self.sign_in()
        old_key = self.client.session.session_key
        response = self.client.post(self.logout_url, secure=True)
        self.assertRedirects(response, reverse('core:home'))
        self.assertFalse(Session.objects.filter(session_key=old_key).exists())
        self.assertNotIn('_auth_user_id', self.client.session)
        attacker = Client()
        attacker.cookies[settings.SESSION_COOKIE_NAME] = old_key
        self.assertEqual(attacker.get(self.protected_url, secure=True).status_code, 302)

    def test_get_does_not_log_user_out(self):
        self.sign_in()
        self.assertEqual(self.client.get(self.logout_url, secure=True).status_code, 405)
        self.assertEqual(int(self.client.session['_auth_user_id']), self.donor.pk)

    def test_login_and_logout_require_csrf_tokens(self):
        browser = Client(enforce_csrf_checks=True)
        self.assertEqual(self.sign_in(browser).status_code, 403)
        browser.force_login(self.donor)
        self.assertEqual(browser.post(self.logout_url, secure=True).status_code, 403)
        page = browser.get(self.protected_url, secure=True)
        token = page.cookies[settings.CSRF_COOKIE_NAME].value
        response = browser.post(self.logout_url, {'csrfmiddlewaretoken': token}, secure=True)
        self.assertRedirects(response, reverse('core:home'))

    def test_login_rotates_preexisting_session_key(self):
        session = self.client.session
        session['anonymous_marker'] = True
        session.save()
        old_key = session.session_key
        self.sign_in()
        self.assertNotEqual(self.client.session.session_key, old_key)
        self.assertFalse(Session.objects.filter(session_key=old_key).exists())

    def test_login_response_is_not_cacheable(self):
        response = self.client.get(self.login_url, secure=True)
        self.assertIn('no-store', response.headers.get('Cache-Control', ''))
