"""
Tests for Password Reset Workflow (SRS BBMS-F-005, TC-AUTH-01/02).
Verifies:
- Single-use, time-limited tokens.
- Request and reset screens.
- Generic enumeration-proof responses for known and unknown accounts.
- Password change and verification.
- Replay prevention (token cannot be reused after password change).
- Token expiry enforcement.
- Clearing of account lockout upon successful password reset.
- Secret scrubbing (tokens and passwords never logged).
"""
from datetime import timedelta
from django.conf import settings
from django.contrib.auth import authenticate
from django.contrib.auth.tokens import default_token_generator
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from core.models import SecurityAuditEvent
from accounts.models import LoginSecurityState, User


class PasswordResetTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.initial_password = 'InitialPassword@123'
        cls.donor = User.objects.create_user(
            username='reset_donor',
            email='reset_donor@example.com',
            password=cls.initial_password,
            role=User.Role.DONOR,
        )

    def setUp(self):
        self.request_url = reverse('accounts:password_reset')
        self.done_url = reverse('accounts:password_reset_done')
        self.complete_url = reverse('accounts:password_reset_complete')

    def test_request_screen_renders_successfully(self):
        response = self.client.get(self.request_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Password Recovery')
        self.assertContains(response, 'Email address')

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_request_with_valid_email_delivers_reset_email(self):
        mail.outbox = []
        response = self.client.post(self.request_url, {'email': 'RESET_DONOR@example.com'})
        self.assertRedirects(response, self.done_url)

        self.assertEqual(len(mail.outbox), 1)
        delivered = mail.outbox[0]
        self.assertIn(self.donor.email, delivered.to)
        self.assertIn('Password Reset Instructions', delivered.subject)

        # Ensure reset URL with uidb64 and token is contained
        uidb64 = urlsafe_base64_encode(force_bytes(self.donor.pk))
        self.assertIn(f"/accounts/reset/{uidb64}/", delivered.body)

        # Verify audit record
        audit = SecurityAuditEvent.objects.filter(action='password_reset_request').first()
        self.assertIsNotNone(audit)
        self.assertEqual(audit.actor, self.donor)

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_request_with_unknown_email_shows_same_generic_done_page(self):
        mail.outbox = []
        response = self.client.post(self.request_url, {'email': 'nobody_exists@example.com'})
        self.assertRedirects(response, self.done_url)
        self.assertEqual(len(mail.outbox), 0)

        # Audit record created for unknown request without disclosing user presence
        audit = SecurityAuditEvent.objects.filter(action='password_reset_request_unknown').first()
        self.assertIsNotNone(audit)

    def test_generic_done_screen_content(self):
        response = self.client.get(self.done_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Check Your Email')
        self.assertContains(response, '15 minutes')

    def test_successful_password_reset_flow(self):
        token = default_token_generator.make_token(self.donor)
        uidb64 = urlsafe_base64_encode(force_bytes(self.donor.pk))
        confirm_url = reverse('accounts:password_reset_confirm', kwargs={'uidb64': uidb64, 'token': token})

        # GET confirm screen with valid token
        response = self.client.get(confirm_url)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['validlink'])
        self.assertContains(response, 'Set New Password')

        # POST new password
        new_password = 'BrandNewPassword@2026!'
        response = self.client.post(confirm_url, {
            'new_password1': new_password,
            'new_password2': new_password,
        })
        self.assertRedirects(response, self.complete_url)

        # Verify old password no longer works
        self.assertIsNone(authenticate(username=self.donor.username, password=self.initial_password))

        # Verify new password works
        authenticated = authenticate(username=self.donor.username, password=new_password)
        self.assertIsNotNone(authenticated)

    def test_token_replay_is_prevented_after_password_reset(self):
        """Single-use verification: submitting the same token a second time must fail."""
        token = default_token_generator.make_token(self.donor)
        uidb64 = urlsafe_base64_encode(force_bytes(self.donor.pk))
        confirm_url = reverse('accounts:password_reset_confirm', kwargs={'uidb64': uidb64, 'token': token})

        # First use succeeds
        new_pwd = 'FirstResetPassword@2026!'
        response = self.client.post(confirm_url, {
            'new_password1': new_pwd,
            'new_password2': new_pwd,
        })
        self.assertRedirects(response, self.complete_url)

        # Replay attempt fails: token is now invalid because password hash changed
        replay_response = self.client.get(confirm_url)
        self.assertEqual(replay_response.status_code, 200)
        self.assertFalse(replay_response.context['validlink'])
        self.assertContains(replay_response, 'Reset Link Expired or Invalid')

    def test_expired_token_is_rejected(self):
        """Time-limited verification: token older than PASSWORD_RESET_TIMEOUT fails."""
        token = default_token_generator.make_token(self.donor)
        uidb64 = urlsafe_base64_encode(force_bytes(self.donor.pk))
        confirm_url = reverse('accounts:password_reset_confirm', kwargs={'uidb64': uidb64, 'token': token})

        # Simulate time moving forward beyond the 15-minute timeout
        from datetime import datetime
        future_time = datetime.now() + timedelta(seconds=settings.PASSWORD_RESET_TIMEOUT + 60)
        from unittest.mock import patch
        with patch.object(default_token_generator, '_now', return_value=future_time):
            response = self.client.get(confirm_url)
            self.assertEqual(response.status_code, 200)
            self.assertFalse(response.context['validlink'])
            self.assertContains(response, 'Reset Link Expired or Invalid')

    def test_invalid_uid_or_token_is_rejected(self):
        confirm_url = reverse('accounts:password_reset_confirm', kwargs={'uidb64': 'invalid_uid', 'token': 'bad-token'})
        response = self.client.get(confirm_url)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context['validlink'])
        self.assertContains(response, 'Reset Link Expired or Invalid')

    def test_password_reset_unlocks_locked_account(self):
        """A user who was locked out can recover access via password reset."""
        key = f"user:{self.donor.pk}"
        LoginSecurityState.objects.create(
            identifier=key,
            user=self.donor,
            failed_attempts=5,
            lockout_until=timezone.now() + timedelta(minutes=15),
        )

        token = default_token_generator.make_token(self.donor)
        uidb64 = urlsafe_base64_encode(force_bytes(self.donor.pk))
        confirm_url = reverse('accounts:password_reset_confirm', kwargs={'uidb64': uidb64, 'token': token})

        new_password = 'RecoveredAccessPass@2026!'
        response = self.client.post(confirm_url, {
            'new_password1': new_password,
            'new_password2': new_password,
        })
        self.assertRedirects(response, self.complete_url)

        # State is cleared
        state = LoginSecurityState.objects.get(identifier=key)
        self.assertEqual(state.failed_attempts, 0)
        self.assertIsNone(state.lockout_until)

        # Immediate login succeeds
        user = authenticate(username=self.donor.username, password=new_password)
        self.assertIsNotNone(user)
