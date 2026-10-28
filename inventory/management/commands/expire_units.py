"""
Management command to process and transition overdue blood units to Expired status.
SRS References:
- Section 4.12 (BBMS-F-037, BBMS-F-038, BBMS-F-039): Expiry Handling & FEFO
"""
from datetime import datetime
from django.core.management.base import BaseCommand
from django.utils import timezone

from inventory.services import process_expired_units


class Command(BaseCommand):
    help = (
        "Scans blood inventory and transitions eligible overdue units to Expired status "
        "(SRS BBMS-F-038, BBMS-F-039)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            dest='dry_run',
            default=False,
            help="Simulate the expiry process without altering database records.",
        )
        parser.add_argument(
            '--as-of',
            type=str,
            dest='as_of',
            default=None,
            help="Evaluate expiry as of a specific date/time (ISO format, e.g. '2026-11-01' or '2026-11-01T00:00:00Z').",
        )

    def handle(self, *args, **options):
        dry_run = options.get('dry_run', False)
        as_of_raw = options.get('as_of')

        as_of = None
        if as_of_raw:
            try:
                # Handle YYYY-MM-DD or ISO 8601 strings
                parsed = datetime.fromisoformat(as_of_raw.replace('Z', '+00:00'))
                if timezone.is_naive(parsed):
                    as_of = timezone.make_aware(parsed, timezone.get_current_timezone())
                else:
                    as_of = parsed
            except Exception as exc:
                self.stderr.write(self.style.ERROR(f"Invalid --as-of timestamp '{as_of_raw}': {exc}"))
                return

        mode_str = "[DRY-RUN] " if dry_run else ""
        eval_time = as_of or timezone.now()
        self.stdout.write(
            f"{mode_str}Scanning blood inventory for expired units as of {eval_time:%Y-%m-%d %H:%M:%S %Z}..."
        )

        result = process_expired_units(as_of=as_of, dry_run=dry_run, actor=None)
        count = result['processed_count']
        expired_list = result['expired_units']

        if count == 0:
            self.stdout.write(
                self.style.SUCCESS(f"{mode_str}No overdue blood units found. Inventory is up to date.")
            )
            return

        for item in expired_list:
            expiry_str = item['expiry_date'].strftime('%Y-%m-%d %H:%M') if item['expiry_date'] else 'N/A'
            self.stdout.write(
                f"  - {item['bag_id']} ({item['blood_group']} {item['component_type']}) "
                f"Status: {item['previous_status']} -> {item['new_status']} (Expired: {expiry_str})"
            )

        action_word = "would be expired" if dry_run else "transitioned to Expired"
        self.stdout.write(
            self.style.SUCCESS(
                f"{mode_str}Successfully processed {count} blood unit(s) ({action_word})."
            )
        )
