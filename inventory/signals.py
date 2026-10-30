"""
Database signals for inventory app.
Records central audit events for blood unit lifecycle changes (SRS BBMS-SR-008, BBMS-F-058, Issue #47).
"""
from django.db.models.signals import post_delete
from django.dispatch import receiver
from core.audit import record_audit_event
from .models import BloodUnit


@receiver(post_delete, sender=BloodUnit)
def audit_unit_deletion(sender, instance, **kwargs):
    if getattr(instance, '_audit_deleted_recorded', False):
        return
    record_audit_event(
        action='unit_deleted',
        actor_label='System',
        target_type='blood_unit',
        target_id=instance.bag_id,
        details={
            'blood_group': instance.blood_group,
            'component_type': instance.component_type,
            'status': instance.status,
        },
    )
