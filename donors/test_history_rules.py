from datetime import datetime, timedelta, timezone as dt_timezone

from django.core.exceptions import ImproperlyConfigured
from django.test import TestCase, override_settings

from accounts.models import User
from inventory.models import BloodUnit, BloodUnitStatus, ComponentType
from .services import donation_summary


class DonationIntervalTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.donor = User.objects.create_user('history_donor')
        cls.other = User.objects.create_user('other_history_donor')

    def setUp(self):
        self.now = datetime(2026, 10, 22, 12, tzinfo=dt_timezone.utc)

    def collect(self, days_ago=10, **kwargs):
        return BloodUnit.objects.create(**{
            'donor': self.donor, 'blood_group': 'O+', 'location': 'Central Blood Bank',
            'collection_date': self.now - timedelta(days=days_ago), **kwargs,
        })

    def test_first_time_donor_has_empty_history_and_no_interval_deadline(self):
        summary = donation_summary(self.donor, now=self.now)
        self.assertEqual(summary['total_donations'], 0)
        self.assertIsNone(summary['next_eligible_date'])
        self.assertIsNone(summary['last_donation'])
        self.assertTrue(summary['can_donate_by_interval'])

    def test_default_interval_is_90_days_after_latest_collection(self):
        self.collect(days_ago=150)
        latest = self.collect(days_ago=10)
        summary = donation_summary(self.donor, now=self.now)
        self.assertEqual(summary['last_donation'], latest)
        self.assertEqual(summary['total_donations'], 2)
        self.assertEqual(summary['next_eligible_date'], latest.collection_date.date() + timedelta(days=90))
        self.assertFalse(summary['can_donate_by_interval'])

    def test_exact_interval_boundary_is_inclusive(self):
        self.collect(days_ago=90)
        summary = donation_summary(self.donor, now=self.now)
        self.assertEqual(summary['next_eligible_date'], self.now.date())
        self.assertTrue(summary['can_donate_by_interval'])

    @override_settings(DONATION_MIN_INTERVAL_DAYS=120)
    def test_interval_can_be_configured(self):
        unit = self.collect(days_ago=100)
        summary = donation_summary(self.donor, now=self.now)
        self.assertEqual(summary['minimum_interval_days'], 120)
        self.assertEqual(summary['next_eligible_date'], unit.collection_date.date() + timedelta(days=120))
        self.assertFalse(summary['can_donate_by_interval'])

    def test_future_records_components_and_other_donors_do_not_count(self):
        original = self.collect(days_ago=60)
        self.collect(days_ago=1, parent_unit=original, component_type=ComponentType.RBC)
        self.collect(days_ago=-1)
        self.collect(days_ago=0, donor=self.other)
        summary = donation_summary(self.donor, now=self.now)
        self.assertEqual(list(summary['donations']), [original])
        self.assertEqual(summary['total_donations'], 1)

    def test_discarded_collection_still_counts_as_a_donation(self):
        unit = self.collect(status=BloodUnitStatus.DISCARDED)
        summary = donation_summary(self.donor, now=self.now)
        self.assertEqual(summary['last_donation'], unit)
        self.assertFalse(summary['can_donate_by_interval'])

    @override_settings(TIME_ZONE='Asia/Kolkata')
    def test_interval_uses_configured_local_calendar_date(self):
        collected = datetime(2026, 7, 23, 23, tzinfo=dt_timezone.utc)
        self.collect(collection_date=collected)
        summary = donation_summary(self.donor, now=self.now)
        self.assertEqual(summary['next_eligible_date'].isoformat(), '2026-10-22')

    def test_invalid_interval_configuration_is_rejected(self):
        for value in [0, -1, True, '90']:
            with self.subTest(interval=value), override_settings(DONATION_MIN_INTERVAL_DAYS=value):
                with self.assertRaises(ImproperlyConfigured):
                    donation_summary(self.donor, now=self.now)
