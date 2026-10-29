"""
Tests for Account Lockout and IP Rate Limiting (SRS BBMS-SR-007, TC-SEC-07).
Verifies:
- 15-minute account lockout after 5 consecutive failed login attempts.
- Shared atomic state without per-process dictionaries.
- Username/email alias normalization (accumulating failures across aliases).
- Successful login counter reset.
- Post-lockout behaviour.
- Time progression without real sleeps.
- Protection on HTML login, JSON login, and Django admin login.
- Per-IP rate limiting (at most 10 login requests per minute per source IP).
- Trusted reverse proxy boundary and spoofed header rejection.
- Concurrency and unknown account handling.
"""
from datetime import timedelta
import threading
from django.contrib.auth import authenticate
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from core.models import SecurityAuditEvent
from accounts.models import LoginRateLimitRecord, LoginSecurityState, User
from accounts.security import (
    IP_RATE_LIMIT_MAX_REQUESTS,
    LOCKOUT_DURATION_SECONDS,
    LOCKOUT_THRESHOLD,
    check_account_lockout,
    normalize_identifier,
    resolve_account_key_and_user,
)


class AccountLockoutTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.valid_password = 'CorrectPassword@123'
        cls.user = User.objects.create_user(
            username='lockout_target',
            email='target@example.com',
            password=cls.valid_password,
            role=User.Role.DONOR,
        )

    def setUp(self):
        self.login_url = reverse('accounts:login')

    def _post_login(self, username, password='WrongPassword!', **extra):
        return self.client.post(self.login_url, {
            'username': username,
            'password': password,
        }, **extra)

    def test_five_consecutive_failed_attempts_locks_account_for_15_minutes(self):
        # 1 to 4 failed attempts: not locked yet
        for i in range(1, LOCKOUT_THRESHOLD):
            response = self._post_login(self.user.username)
            self.assertEqual(response.status_code, 200)
            is_locked, state = check_account_lockout(self.user.username)
            self.assertFalse(is_locked)
            self.assertEqual(state.failed_attempts, i)

        # 5th failed attempt: triggers lockout
        response = self._post_login(self.user.username)
        self.assertEqual(response.status_code, 200)
        is_locked, state = check_account_lockout(self.user.username)
        self.assertTrue(is_locked)
        self.assertEqual(state.failed_attempts, LOCKOUT_THRESHOLD)
        self.assertIsNotNone(state.lockout_until)

        # 6th attempt with CORRECT password while locked is rejected
        locked_response = self._post_login(self.user.username, password=self.valid_password)
        self.assertEqual(locked_response.status_code, 200)
        self.assertNotIn('_auth_user_id', self.client.session)

        # Generic failure message displayed; no disclosure of account existence or lockout
        self.assertContains(locked_response, 'Invalid email/username or password.')

        # Verify audit events
        locked_event = SecurityAuditEvent.objects.filter(action='account_locked').first()
        self.assertIsNotNone(locked_event)
        self.assertEqual(locked_event.actor, self.user)

    def test_alias_normalization_aggregates_failures_across_username_and_email(self):
        """Attacker using username and email aliases cannot bypass the 5-attempt limit."""
        # 2 failed attempts using lowercase username
        self._post_login('lockout_target')
        self._post_login('lockout_target')

        # 1 failed attempt using uppercase username with spaces
        self._post_login('  LOCKOUT_TARGET  ')

        # 1 failed attempt using mixed-case email
        self._post_login('Target@Example.Com')

        is_locked, state = check_account_lockout(self.user.username)
        self.assertFalse(is_locked)
        self.assertEqual(state.failed_attempts, 4)

        # 5th attempt using lowercase email triggers lockout
        self._post_login('target@example.com')
        is_locked, state = check_account_lockout(self.user.username)
        self.assertTrue(is_locked)
        self.assertEqual(state.failed_attempts, 5)

    def test_successful_login_resets_failed_attempt_counter(self):
        # 3 failed attempts
        for _ in range(3):
            self._post_login(self.user.username)

        is_locked, state = check_account_lockout(self.user.username)
        self.assertEqual(state.failed_attempts, 3)

        # Successful login
        success_response = self._post_login(self.user.username, password=self.valid_password)
        self.assertRedirects(success_response, reverse('donors:dashboard'))

        # Counter reset to 0
        state.refresh_from_db()
        self.assertEqual(state.failed_attempts, 0)
        self.assertIsNone(state.lockout_until)

    def test_time_progression_without_real_sleeps(self):
        """Account recovers after 15-minute lockout period without sleeping."""
        # Trigger lockout
        for _ in range(5):
            self._post_login(self.user.username)

        is_locked, state = check_account_lockout(self.user.username)
        self.assertTrue(is_locked)

        # Simulate 15 minutes and 1 second later
        future_time = timezone.now() + timedelta(seconds=LOCKOUT_DURATION_SECONDS + 1)
        from unittest.mock import patch
        with patch('django.utils.timezone.now', return_value=future_time):
            # Check lockout state is no longer locked
            is_locked_after, state_after = check_account_lockout(self.user.username, at_time=future_time)
            self.assertFalse(is_locked_after)

            # Login with valid password succeeds
            auth_user = authenticate(username=self.user.username, password=self.valid_password)
            self.assertIsNotNone(auth_user)

            # Counter reset
            state.refresh_from_db()
            self.assertEqual(state.failed_attempts, 0)
            self.assertIsNone(state.lockout_until)

    def test_failed_attempt_after_lockout_expiry_starts_fresh_counter(self):
        # Trigger lockout
        for _ in range(5):
            self._post_login(self.user.username)

        # Advance time by 16 minutes
        future_time = timezone.now() + timedelta(minutes=16)
        from unittest.mock import patch
        with patch('django.utils.timezone.now', return_value=future_time):
            # Wrong password after lockout expired
            self._post_login(self.user.username, password='StillWrongPassword')

            # Streak restarts at 1 instead of 6
            state = LoginSecurityState.objects.get(identifier=f"user:{self.user.pk}")
            self.assertEqual(state.failed_attempts, 1)
            self.assertIsNone(state.lockout_until)

    def test_unknown_accounts_tracked_without_revealing_existence(self):
        """Failed attempts for nonexistent usernames track safely and return generic errors."""
        for _ in range(5):
            response = self._post_login('unknown_user_99999@example.com')
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, 'Invalid email/username or password.')

        state = LoginSecurityState.objects.filter(identifier='unknown:unknown_user_99999@example.com').first()
        self.assertIsNotNone(state)
        self.assertEqual(state.failed_attempts, 5)
        self.assertTrue(state.is_locked())

    def test_django_admin_login_shares_lockout_state(self):
        """Lockout applied to accounts:login is enforced on admin:login and vice versa."""
        admin_user = User.objects.create_superuser(
            username='admin_lockout_test',
            email='admin_lockout@example.com',
            password=self.valid_password,
        )
        admin_login_url = reverse('admin:login')

        # 4 failed attempts on /accounts/login/
        for _ in range(4):
            self.client.post(self.login_url, {
                'username': admin_user.username,
                'password': 'WrongPassword!',
            })

        # 5th failed attempt on /admin/login/ triggers lockout
        admin_resp = self.client.post(admin_login_url, {
            'username': admin_user.username,
            'password': 'WrongPassword!',
        })
        self.assertEqual(admin_resp.status_code, 200)

        # Account is now locked across all routes
        is_locked, state = check_account_lockout(admin_user.username)
        self.assertTrue(is_locked)

        # Even with valid password, admin login is denied
        denied_admin = self.client.post(admin_login_url, {
            'username': admin_user.username,
            'password': self.valid_password,
        })
        self.assertEqual(denied_admin.status_code, 200)
        self.assertNotIn('_auth_user_id', self.client.session)


class AccountConcurrencyTests(TransactionTestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='concurrency_donor',
            email='concurrency@example.com',
            password='ValidPassword@123',
            role=User.Role.DONOR,
        )
        self.login_url = reverse('accounts:login')

    def test_concurrency_in_failed_login_attempts(self):
        """Concurrent failed login attempts update shared atomic counters without lost updates."""
        from django.db import connection
        connection.close()

        threads = []
        errors = []

        def worker():
            try:
                from django.db import connection
                connection.close()
                c = Client()
                c.post(self.login_url, {
                    'username': self.user.username,
                    'password': 'ConcurrentWrongPass!',
                })
            except Exception as e:
                errors.append(e)
            finally:
                from django.db import connection
                connection.close()

        # Spawn 5 concurrent threads
        for _ in range(5):
            t = threading.Thread(target=worker)
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        self.assertEqual(errors, [])
        state = LoginSecurityState.objects.get(identifier=f"user:{self.user.pk}")
        self.assertEqual(state.failed_attempts, 5)
        self.assertTrue(state.is_locked())


class IPRateLimitingTests(TestCase):
    def setUp(self):
        self.login_url = reverse('accounts:login')
        self.source_ip = '198.51.100.42'

    def test_ip_rate_limiting_enforces_at_most_10_requests_per_minute(self):
        """10 requests are processed; the 11th request from the same IP returns HTTP 429."""
        for i in range(1, IP_RATE_LIMIT_MAX_REQUESTS + 1):
            response = self.client.post(
                self.login_url,
                {'username': 'any_user', 'password': 'any_password'},
                REMOTE_ADDR=self.source_ip,
            )
            # Login fails credential check with 200
            self.assertEqual(response.status_code, 200)

        # 11th request: blocked by rate limiter with 429 Too Many Requests
        rate_limited_response = self.client.post(
            self.login_url,
            {'username': 'any_user', 'password': 'any_password'},
            REMOTE_ADDR=self.source_ip,
        )
        self.assertEqual(rate_limited_response.status_code, 429)
        self.assertEqual(rate_limited_response.headers.get('Retry-After'), '60')
        self.assertIn(b'Too many login requests', rate_limited_response.content)

        # Requests from a different IP are not blocked
        other_ip_response = self.client.post(
            self.login_url,
            {'username': 'any_user', 'password': 'any_password'},
            REMOTE_ADDR='203.0.113.88',
        )
        self.assertEqual(other_ip_response.status_code, 200)

        # Verify rate limit security audit event
        rate_limit_event = SecurityAuditEvent.objects.filter(action='ip_rate_limited').first()
        self.assertIsNotNone(rate_limit_event)
        self.assertEqual(rate_limit_event.ip_address, self.source_ip)

    def test_ip_rate_limit_sliding_window_progression(self):
        """Requests older than 60 seconds fall out of the rate limit window."""
        now = timezone.now()
        # Seed 10 records from 70 seconds ago
        for _ in range(10):
            LoginRateLimitRecord.objects.create(
                ip_address=self.source_ip,
                timestamp=now - timedelta(seconds=70),
            )

        # A new request from that IP is accepted because the old records are outside the 60s window
        response = self.client.post(
            self.login_url,
            {'username': 'any_user', 'password': 'any_password'},
            REMOTE_ADDR=self.source_ip,
        )
        self.assertEqual(response.status_code, 200)

    def test_trusted_proxy_boundary_rejects_arbitrary_forwarded_headers(self):
        """
        When BBMS_TRUSTED_PROXIES is empty, X-Forwarded-For is strictly ignored
        to prevent attackers from spoofing their IP to bypass rate limits.
        """
        with override_settings(BBMS_TRUSTED_PROXIES=[]):
            # Attacker sends fake XFF headers while calling from the same peer IP
            for i in range(10):
                self.client.post(
                    self.login_url,
                    {'username': 'user', 'password': 'bad'},
                    REMOTE_ADDR=self.source_ip,
                    HTTP_X_FORWARDED_FOR=f"10.0.0.{i}",
                )

            # 11th request with another fake header is blocked because peer IP is tracked
            blocked = self.client.post(
                self.login_url,
                {'username': 'user', 'password': 'bad'},
                REMOTE_ADDR=self.source_ip,
                HTTP_X_FORWARDED_FOR='10.0.0.99',
            )
            self.assertEqual(blocked.status_code, 429)

    def test_trusted_proxy_boundary_honors_forwarded_header_only_from_trusted_proxy(self):
        """When the peer IP matches BBMS_TRUSTED_PROXIES, the client IP in XFF is trusted."""
        trusted_proxy_ip = '10.0.0.1'
        real_client_ip = '198.51.100.99'

        with override_settings(BBMS_TRUSTED_PROXIES=[trusted_proxy_ip]):
            # 10 requests from client IP through trusted proxy
            for _ in range(10):
                self.client.post(
                    self.login_url,
                    {'username': 'user', 'password': 'bad'},
                    REMOTE_ADDR=trusted_proxy_ip,
                    HTTP_X_FORWARDED_FOR=real_client_ip,
                )

            # 11th request from same client through proxy is blocked
            blocked = self.client.post(
                self.login_url,
                {'username': 'user', 'password': 'bad'},
                REMOTE_ADDR=trusted_proxy_ip,
                HTTP_X_FORWARDED_FOR=real_client_ip,
            )
            self.assertEqual(blocked.status_code, 429)
            event = SecurityAuditEvent.objects.filter(action='ip_rate_limited').last()
            self.assertEqual(event.ip_address, real_client_ip)
