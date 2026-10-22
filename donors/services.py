"""Donor history and donation-interval rules (BBMS-F-007 and BBMS-F-008)."""
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.utils import timezone


def donation_summary(donor, *, now=None):
    """Summarize completed collections, never derived component inventory rows.

    A stored top-level collection represents a completed donation regardless of
    subsequent serology/disposal. Future-dated records are not past donations.
    The interval is a calendar-day rule in the configured application time zone;
    it is independent of the donor's medical-screening result.
    """
    from inventory.models import BloodUnit

    interval = settings.DONATION_MIN_INTERVAL_DAYS
    if isinstance(interval, bool) or not isinstance(interval, int) or interval <= 0:
        raise ImproperlyConfigured('DONATION_MIN_INTERVAL_DAYS must be a positive integer.')
    now = now or timezone.now()
    donations = BloodUnit.objects.filter(
        donor=donor, parent_unit__isnull=True, collection_date__lte=now,
    ).order_by('-collection_date', '-pk')
    last_donation = donations.first()
    next_date = None
    if last_donation is not None:
        collected = timezone.localtime(last_donation.collection_date).date()
        next_date = collected + timedelta(days=interval)
    return {
        'donations': donations,
        'last_donation': last_donation,
        'total_donations': donations.count(),
        'next_eligible_date': next_date,
        'minimum_interval_days': interval,
        'can_donate_by_interval': next_date is None or timezone.localdate(now) >= next_date,
    }
