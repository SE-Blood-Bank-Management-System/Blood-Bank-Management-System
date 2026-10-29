"""
Core models for cross-cutting BBMS infrastructure (SRS BBMS-SR-008, BBMS-F-058).
"""
from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.db import models
from django.utils import timezone


class SecurityAuditEvent(models.Model):
    """
    Central append-only, tamper-evident security audit event record (SRS BBMS-SR-008, BBMS-F-058).
    Captures actor/system identity, security actions, timestamps, and safe metadata
    without persisting credentials, tokens, or unnecessary secrets.
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

    class Meta:
        ordering = ['-timestamp', '-id']
        indexes = [
            models.Index(fields=['action', 'timestamp']),
            models.Index(fields=['ip_address', 'timestamp']),
        ]

    def save(self, *args, **kwargs):
        if self.pk and not kwargs.get('force_insert', False):
            raise PermissionDenied('Security audit events are append-only and cannot be modified.')
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionDenied('Security audit events are tamper-evident and cannot be deleted.')

    def __str__(self):
        actor = self.actor_label or (self.actor.username if self.actor else 'anonymous')
        return f"[{self.timestamp.isoformat()}] {self.severity} {self.action} by {actor} ({self.ip_address or 'no-ip'})"
