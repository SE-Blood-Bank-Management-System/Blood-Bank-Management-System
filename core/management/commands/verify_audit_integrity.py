"""
Django management command for verifying cryptographic audit log integrity.
SRS BBMS-SR-008, BBMS-F-058, Issue #47.
"""
from django.core.management.base import BaseCommand, CommandError
from core.audit import verify_audit_log_integrity


class Command(BaseCommand):
    help = 'Cryptographically verifies the central tamper-evident audit log hash chain (SRS BBMS-SR-008, BBMS-F-058).'

    def add_arguments(self, parser):
        parser.add_argument(
            '--verbose',
            action='store_true',
            help='Display detailed verification status for every audit record.',
        )
        parser.add_argument(
            '--quiet',
            action='store_true',
            help='Suppress standard output, returning exit status only (0 = valid, 1 = tampered).',
        )

    def handle(self, *args, **options):
        verbose = options.get('verbose', False)
        quiet = options.get('quiet', False)

        is_valid, errors, count = verify_audit_log_integrity()

        if is_valid:
            if not quiet:
                self.stdout.write(
                    self.style.SUCCESS(
                        f"AUDIT INTEGRITY OK: Successfully verified {count} audit record(s). "
                        f"Cryptographic SHA-256 hash chain is intact and tamper-free."
                    )
                )
                if verbose and count > 0:
                    self.stdout.write(f"Verified {count} record(s) from genesis hash 0*64.")
        else:
            if not quiet:
                self.stdout.write(
                    self.style.ERROR(
                        f"AUDIT INTEGRITY VIOLATION DETECTED: Found {len(errors)} error(s) "
                        f"across {count} audit records!"
                    )
                )
                for err in errors:
                    self.stdout.write(self.style.ERROR(f"  - {err}"))
            raise CommandError(f"Audit log integrity check failed with {len(errors)} violation(s).")
