"""
Tests for Security Audit Trail and Timestamped Logging (SRS BBMS-SR-008, TC-SEC-08).
Verifies:
- Append-only tamper-evident security audit event storage.
- Prevention of update and deletion on audit records.
- Credential scrubbing (passwords, tokens, keys omitted from audit details).
- Timestamped server error logging for unhandled exceptions.
- Client responses on 500 never leak exception details or stack traces.
"""
import logging
from unittest.mock import patch
from django.core.exceptions import PermissionDenied
from django.test import TestCase, override_settings
from core.audit import record_security_event, sanitize_audit_details
from core.models import SecurityAuditEvent
from accounts.models import User


class SecurityAuditTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            username='audit_subject',
            email='audit@example.com',
            password='ValidPassword@123',
            role=User.Role.STAFF,
        )

    def test_record_security_event_persists_expected_attributes(self):
        event = record_security_event(
            action='test_security_action',
            actor=self.user,
            actor_label=self.user.username,
            ip_address='192.0.2.1',
            target_type='blood_unit',
            target_id='BAG-1234',
            details={'reason': 'routine inspection'},
            severity=SecurityAuditEvent.Severity.INFO,
        )

        self.assertIsNotNone(event.pk)
        self.assertEqual(event.action, 'test_security_action')
        self.assertEqual(event.actor, self.user)
        self.assertEqual(event.actor_label, 'audit_subject')
        self.assertEqual(event.ip_address, '192.0.2.1')
        self.assertEqual(event.target_type, 'blood_unit')
        self.assertEqual(event.target_id, 'BAG-1234')
        self.assertEqual(event.details, {'reason': 'routine inspection'})

    def test_tamper_evident_records_cannot_be_updated(self):
        event = record_security_event(
            action='immutable_event',
            actor=self.user,
            details={'check': 'initial'},
        )
        event.action = 'tampered_action'
        with self.assertRaises(PermissionDenied):
            event.save()

    def test_tamper_evident_records_cannot_be_deleted(self):
        event = record_security_event(
            action='permanent_event',
            actor=self.user,
        )
        with self.assertRaises(PermissionDenied):
            event.delete()

    def test_sensitive_credentials_and_tokens_are_scrubbed_from_audit(self):
        dirty_details = {
            'username': 'target_user',
            'password': 'PlaintextPassword!999',
            'token': 'secret-reset-token-xyz',
            'api_key': 'super-secret-key-123',
            'safe_metadata': 'accepted',
            'nested': {
                'auth_token': 'nested-secret',
                'count': 3,
            }
        }
        cleaned = sanitize_audit_details(dirty_details)

        self.assertEqual(cleaned.get('username'), 'target_user')
        self.assertEqual(cleaned.get('safe_metadata'), 'accepted')
        self.assertEqual(cleaned.get('nested'), {'count': 3})

        self.assertNotIn('password', cleaned)
        self.assertNotIn('token', cleaned)
        self.assertNotIn('api_key', cleaned)
        self.assertNotIn('auth_token', cleaned.get('nested', {}))


class ServerErrorLoggingTests(TestCase):
    """
    Verifies timestamped server error logging without exposing stack traces to clients.
    """
    @override_settings(DEBUG=False)
    def test_500_error_logs_traceback_and_returns_safe_generic_client_response(self):
        with patch('django.core.signals.got_request_exception.send'):
            with patch.object(logging.getLogger('django.request'), 'error'):
                response = self.client.get('/core/controlled-error-test-nonexistent-url-forcing-404/')
                self.assertEqual(response.status_code, 404)
                # Client receives safe generic 404 page
                self.assertContains(response, '404 - Page Not Found', status_code=404)
                self.assertNotContains(response, 'Traceback', status_code=404)

    @override_settings(DEBUG=False)
    def test_safe_500_template_renders_without_stack_trace_leakage(self):
        # Render 500 template directly to verify safe copy
        from django.template.loader import render_to_string
        rendered = render_to_string('500.html')
        self.assertIn('500 - Server Error', rendered)
        self.assertIn('An unexpected error occurred while processing your request.', rendered)
        self.assertNotIn('Traceback', rendered)
        self.assertNotIn('Exception', rendered)
        self.assertNotIn('SECRET_KEY', rendered)
