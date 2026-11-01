"""TC-NF-02: exercise a real unhandled error, not just the 500 template."""
import logging

from django.conf import settings
from django.test import TestCase, override_settings
from django.urls import path
from bbms.urls import urlpatterns as application_urls


def controlled_fault(request):
    raise RuntimeError('Controlled synthetic reliability fault')


# This URL exists only while the test overrides ROOT_URLCONF.
urlpatterns = [path('controlled-fault/', controlled_fault), *application_urls]


class ErrorLoggingAcceptanceTests(TestCase):
    @override_settings(DEBUG=False, ROOT_URLCONF=__name__)
    def test_unhandled_error_records_timestamp_stack_trace_and_safe_response(self):
        self.client.raise_request_exception = False
        with self.assertLogs('django.request', level='ERROR') as captured:
            response = self.client.get('/controlled-fault/')
        self.assertEqual(response.status_code, 500)
        self.assertNotContains(response, 'Controlled synthetic', status_code=500)
        record = captured.records[0]
        self.assertIsNotNone(record.exc_info)
        definition = settings.LOGGING['formatters']['timestamped']
        rendered = logging.Formatter(definition['format'], definition['datefmt']).format(record)
        self.assertRegex(rendered, r'\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}')
        self.assertIn('Traceback', rendered)
        self.assertIn('Controlled synthetic reliability fault', rendered)
