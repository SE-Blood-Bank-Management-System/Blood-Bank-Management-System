"""
Database signals for requisitions app.
Records central audit events for requisition lifecycle changes (SRS BBMS-SR-008, BBMS-F-058, Issue #47).
"""
from django.db.models.signals import post_delete
from django.dispatch import receiver
from core.audit import record_audit_event
from .models import Requisition


@receiver(post_delete, sender=Requisition)
def audit_requisition_deletion(sender, instance, **kwargs):
    record_audit_event(
        action='requisition_deleted',
        actor_label='System',
        target_type='requisition',
        target_id=instance.requisition_id,
        details={
            'hospital': instance.hospital.username if instance.hospital else '',
            'blood_group': instance.blood_group,
            'component_type': instance.component_type,
            'status': instance.status,
        },
    )
