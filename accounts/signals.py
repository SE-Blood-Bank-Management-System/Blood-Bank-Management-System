"""
Database signals for accounts app.
Records central audit events for user lifecycle changes (SRS BBMS-SR-008, BBMS-F-058, Issue #47).
"""
from django.db.models.signals import post_delete
from django.dispatch import receiver
from core.audit import record_audit_event
from .models import User


@receiver(post_delete, sender=User)
def audit_user_deletion(sender, instance, **kwargs):
    if getattr(instance, '_audit_deleted_recorded', False):
        return
    record_audit_event(
        action='user_deleted',
        actor_label='System',
        target_type='user',
        target_id=str(instance.pk),
        details={'username': instance.username, 'role': instance.role},
    )
