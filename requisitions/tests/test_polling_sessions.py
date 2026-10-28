from datetime import timedelta
from unittest.mock import patch

from django.conf import settings
from django.contrib.sessions.models import Session
from django.urls import reverse
from django.utils import timezone

from .base import RequestTestCase


class PassivePollingSessionTests(RequestTestCase):
    def setUp(self):
        self.client.force_login(self.staff)
        self.key = self.client.session.session_key
        self.started = timezone.now()

    def test_poll_cannot_extend_idle_session_and_expired_cookie_is_cleared(self):
        before = Session.objects.get(session_key=self.key).expire_date
        url = reverse('requisitions:stat_alerts')
        with patch('django.utils.timezone.now', return_value=self.started + timedelta(minutes=29)):
            response = self.client.get(url, HTTP_ACCEPT='application/json', secure=True)
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(settings.SESSION_COOKIE_NAME, response.cookies)
        self.assertEqual(Session.objects.get(session_key=self.key).expire_date, before)
        with patch('django.utils.timezone.now', return_value=self.started + timedelta(minutes=31)):
            response = self.client.get(url, HTTP_ACCEPT='application/json', secure=True)
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.cookies[settings.SESSION_COOKIE_NAME]['max-age'], 0)

    def test_interactive_page_request_still_renews_inactivity_expiry(self):
        with patch('django.utils.timezone.now', return_value=self.started + timedelta(minutes=29)):
            response = self.client.get(reverse('requisitions:list'), secure=True)
        self.assertEqual(response.status_code, 200)
        after = Session.objects.get(session_key=self.key).expire_date
        self.assertGreater(after, self.started + timedelta(minutes=58))
        with patch('django.utils.timezone.now', return_value=self.started + timedelta(minutes=35)):
            self.assertEqual(self.client.get(reverse('requisitions:stat_alerts'), secure=True).status_code, 200)
