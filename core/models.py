"""
Core models for cross-cutting BBMS infrastructure (SRS BBMS-SR-008, BBMS-F-058).
"""
from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.db import models
from django.utils import timezone


class SecurityAuditEventQuerySet(models.QuerySet):
    """
    Immutable QuerySet for SecurityAuditEvent enforcing append-only semantics.
    SRS BBMS-SR-008, BBMS-F-058.
    """
    def update(self, **kwargs):
        # Allow account deletion to set actor FK to NULL while preserving actor_label
        if kwargs == {'actor': None}:
            return super().update(**kwargs)
        raise PermissionDenied('Security audit events are append-only and cannot be modified.')

    def delete(self):
        raise PermissionDenied('Security audit events are tamper-evident and cannot be deleted.')

    def bulk_update(self, objs, fields, batch_size=None):
        raise PermissionDenied('Security audit events are append-only and cannot be modified.')

    def bulk_create(self, objs, batch_size=None, ignore_conflicts=False, update_conflicts=False,
                    update_fields=None, unique_fields=None):
        if ignore_conflicts or update_conflicts:
            raise PermissionDenied('Security audit events cannot be overwritten or conflict-skipped.')
        return super().bulk_create(objs, batch_size=batch_size)


class SecurityAuditEvent(models.Model):
    """
    Central append-only, tamper-evident security and domain audit event record (SRS BBMS-SR-008, BBMS-F-058).
    Captures actor/system identity, actions, server timestamps, target entity references, and safe metadata
    with cryptographic SHA-256 hash chaining to ensure tamper evidence.
    """
    class Severity(models.TextChoices):
        INFO = 'INFO', 'Info'
        WARNING = 'WARNING', 'Warning'
        ERROR = 'ERROR', 'Error'
        CRITICAL = 'CRITICAL', 'Critical'

    timestamp = models.DateTimeField(default=timezone.now, db_index=True)
    action = models.CharField(max_length=64, db_index=True)
    severity = models.CharField(max_length=16, choices=Severity.choices, default=Severity.INFO)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='security_audit_events',
        help_text='Authenticated user associated with this event, if any.',
    )
    actor_label = models.CharField(
        max_length=255,
        blank=True,
        help_text='Actor username or identifier captured at event time.',
    )
    ip_address = models.GenericIPAddressField(null=True, blank=True, db_index=True)
    user_agent = models.CharField(max_length=512, blank=True)
    target_type = models.CharField(max_length=64, blank=True)
    target_id = models.CharField(max_length=64, blank=True)
    details = models.JSONField(default=dict, blank=True)

    # Verifiable cryptographic tamper evidence (BBMS-SR-008, BBMS-F-058)
    prev_hash = models.CharField(
        max_length=64,
        blank=True,
        default='',
        db_index=True,
        help_text='Cryptographic SHA-256 hash of the immediately preceding audit record.',
    )
    record_hash = models.CharField(
        max_length=64,
        blank=True,
        default='',
        db_index=True,
        help_text='Cryptographic SHA-256 hash sealing this audit record and chain link.',
    )

    objects = SecurityAuditEventQuerySet.as_manager()

    class Meta:
        ordering = ['-timestamp', '-id']
        indexes = [
            models.Index(fields=['action', 'timestamp']),
            models.Index(fields=['ip_address', 'timestamp']),
            models.Index(fields=['target_type', 'target_id']),
        ]

    def save(self, *args, **kwargs):
        # Deny modification if the record already exists
        if not self._state.adding or (self.pk is not None and type(self).objects.filter(pk=self.pk).exists()):
            raise PermissionDenied('Security audit events are append-only and cannot be modified.')

        if not self.record_hash:
            from .audit import calculate_event_hash, GENESIS_PREV_HASH
            if not self.prev_hash:
                last_record = SecurityAuditEvent.objects.order_by('id').last()
                self.prev_hash = last_record.record_hash if (last_record and last_record.record_hash) else GENESIS_PREV_HASH
            if not self.timestamp:
                self.timestamp = timezone.now()
            self.record_hash = calculate_event_hash(
                prev_hash=self.prev_hash,
                timestamp=self.timestamp,
                action=self.action,
                severity=self.severity,
                actor_label=self.actor_label,
                ip_address=self.ip_address,
                target_type=self.target_type,
                target_id=self.target_id,
                details=self.details,
            )

        kwargs['force_insert'] = True
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionDenied('Security audit events are tamper-evident and cannot be deleted.')

    def __str__(self):
        actor = self.actor_label or (self.actor.username if self.actor else 'System')
        return f"[{self.timestamp.isoformat()}] {self.severity} {self.action} by {actor} ({self.ip_address or 'no-ip'})"
