"""
Demonstration of actual SMTP message delivery (SRS BBMS-F-005, Acceptance Criteria).
Starts a local RFC 5321 SMTP TCP server on an ephemeral loopback port,
points Django's standard SMTP EmailBackend to it, and triggers a password reset.
Verifies full TCP handshake, SMTP dialogue, and RFC 5322 payload delivery.
"""
import socketserver
import threading
from django.test import TestCase, override_settings
from django.urls import reverse
from accounts.models import User


class _TestSMTPHandler(socketserver.StreamRequestHandler):
    def handle(self):
        # 1. Greeting banner
        self.wfile.write(b"220 127.0.0.1 BBMS Mock SMTP Service Ready\r\n")
        self.wfile.flush()

        in_data = False
        data_lines = []

        while True:
            line = self.rfile.readline()
            if not line:
                break
            line_str = line.decode('utf-8', errors='replace').rstrip('\r\n')

            if in_data:
                if line_str == '.':
                    in_data = False
                    full_payload = '\n'.join(data_lines)
                    self.server.received_messages.append(full_payload)
                    self.wfile.write(b"250 2.0.0 Ok: queued in test delivery\r\n")
                    self.wfile.flush()
                else:
                    data_lines.append(line_str)
                continue

            upper = line_str.upper()
            if upper.startswith(('EHLO', 'HELO')):
                self.wfile.write(b"250-127.0.0.1\r\n250 HELP\r\n")
            elif upper.startswith('MAIL FROM:'):
                self.wfile.write(b"250 2.1.0 Sender ok\r\n")
            elif upper.startswith('RCPT TO:'):
                self.wfile.write(b"250 2.1.5 Recipient ok\r\n")
            elif upper.startswith('DATA'):
                in_data = True
                data_lines = []
                self.wfile.write(b"354 Start mail input; end with <CR><LF>.<CR><LF>\r\n")
            elif upper.startswith('QUIT'):
                self.wfile.write(b"221 2.0.0 Service closing transmission channel\r\n")
                self.wfile.flush()
                break
            elif upper.startswith('RSET'):
                self.wfile.write(b"250 2.0.0 Reset state ok\r\n")
            elif upper.startswith('NOOP'):
                self.wfile.write(b"250 2.0.0 Noop ok\r\n")
            else:
                self.wfile.write(b"500 5.5.1 Command unrecognized\r\n")
            self.wfile.flush()


class _TestSMTPServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True

    def __init__(self, server_address, RequestHandlerClass):
        self.received_messages = []
        super().__init__(server_address, RequestHandlerClass)


class SMTPDeliveryDemonstrationTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Bind to loopback port 0 (OS allocates ephemeral free port)
        cls.smtp_server = _TestSMTPServer(('127.0.0.1', 0), _TestSMTPHandler)
        cls.server_port = cls.smtp_server.server_address[1]
        cls.server_thread = threading.Thread(target=cls.smtp_server.serve_forever, daemon=True)
        cls.server_thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.smtp_server.shutdown()
        cls.smtp_server.server_close()
        cls.server_thread.join(timeout=2)
        super().tearDownClass()

    def setUp(self):
        self.smtp_server.received_messages.clear()
        self.donor = User.objects.create_user(
            username='smtp_donor',
            email='smtp_donor@example.com',
            password='TestPassword@123',
            role=User.Role.DONOR,
        )

    def test_actual_smtp_message_delivery_over_tcp(self):
        """
        Demonstrates live SMTP delivery over TCP socket using Django's SMTP EmailBackend.
        """
        with override_settings(
            EMAIL_BACKEND='django.core.mail.backends.smtp.EmailBackend',
            EMAIL_HOST='127.0.0.1',
            EMAIL_PORT=self.server_port,
            EMAIL_USE_TLS=False,
            EMAIL_USE_SSL=False,
            EMAIL_TIMEOUT=5,
            DEFAULT_FROM_EMAIL='noreply@bbms.local',
        ):
            response = self.client.post(
                reverse('accounts:password_reset'),
                {'email': self.donor.email}
            )
            self.assertRedirects(response, reverse('accounts:password_reset_done'))

            # Verify the local SMTP TCP server received the real message
            self.assertEqual(len(self.smtp_server.received_messages), 1)
            raw_email = self.smtp_server.received_messages[0]

            self.assertIn('Subject: BBMS - Password Reset Instructions', raw_email)
            self.assertIn(f"To: {self.donor.email}", raw_email)
            self.assertIn('From: noreply@bbms.local', raw_email)
            self.assertIn('/accounts/reset/', raw_email)
            self.assertIn('15 minutes', raw_email)
