"""Hospital requests and their auditable decisions (BBMS-F-042 through F-048)."""
import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models

from core.constants import BloodGroup
from inventory.models import ComponentType


def generate_requisition_id():
    return f'REQ-{uuid.uuid4().hex.upper()}'


class Requisition(models.Model):
    class Status(models.TextChoices):
        PENDING = 'Pending', 'Pending'
        APPROVED = 'Approved', 'Approved'
        PARTIALLY_FULFILLED = 'Partially Fulfilled', 'Partially Fulfilled'
        FULFILLED = 'Fulfilled', 'Fulfilled'
        REJECTED = 'Rejected', 'Rejected'

    requisition_id = models.CharField(max_length=36, unique=True, default=generate_requisition_id, editable=False)
    hospital = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='requisitions')
    # Use the canonical values as labels until the shared B+ label is corrected in #43.
    blood_group = models.CharField(max_length=5, choices=[(value, value) for value in BloodGroup.values])
    component_type = models.CharField(max_length=30, choices=ComponentType.choices)
    quantity = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    required_by = models.DateField()
    is_stat = models.BooleanField(default=False, db_index=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING, editable=False)
    rejection_reason = models.TextField(blank=True, editable=False)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='reviewed_requisitions',
        null=True, blank=True, editable=False,
    )
    reviewed_at = models.DateTimeField(null=True, blank=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    version = models.PositiveIntegerField(default=0, editable=False)

    class Meta:
        ordering = ['-is_stat', 'created_at', 'pk']
        indexes = [models.Index(fields=['status', 'is_stat', 'created_at'], name='request_queue_idx')]
        constraints = [
            models.CheckConstraint(condition=models.Q(quantity__gte=1), name='request_positive_quantity'),
            models.CheckConstraint(condition=models.Q(status__in=[
                'Pending', 'Approved', 'Partially Fulfilled', 'Fulfilled', 'Rejected',
            ]), name='request_valid_status'),
            models.CheckConstraint(
                condition=~models.Q(status='Rejected') | ~models.Q(rejection_reason=''),
                name='request_rejection_reason',
            ),
        ]

    @property
    def dispatched_quantity(self):
        if hasattr(self, '_dispatched_quantity'):
            return self._dispatched_quantity
        return self.fulfilments.count()

    @property
    def remaining_quantity(self):
        return self.quantity - self.dispatched_quantity

    def __str__(self):
        return self.requisition_id


class AppendOnlyQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ValidationError('Requisition history is append-only.')

    def bulk_update(self, objs, fields, batch_size=None):
        raise ValidationError('Requisition history is append-only.')

    def delete(self):
        raise ValidationError('Requisition history cannot be deleted.')


class AppendOnlyModel(models.Model):
    objects = AppendOnlyQuerySet.as_manager()

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError('Requisition history is append-only.')
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError('Requisition history cannot be deleted.')


class RequisitionEvent(AppendOnlyModel):
    class Action(models.TextChoices):
        SUBMITTED = 'Submitted', 'Submitted'
        APPROVED = 'Approved', 'Approved'
        REJECTED = 'Rejected', 'Rejected'
        PRIORITY_CHANGED = 'Priority changed', 'Priority changed'
        DISPATCH_RECORDED = 'Dispatch recorded', 'Dispatch recorded'

    requisition = models.ForeignKey(Requisition, on_delete=models.PROTECT, related_name='events')
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='requisition_events')
    actor_label = models.CharField(max_length=150)
    action = models.CharField(max_length=30, choices=Action.choices)
    previous_status = models.CharField(max_length=20, blank=True)
    new_status = models.CharField(max_length=20)
    previous_is_stat = models.BooleanField(null=True)
    new_is_stat = models.BooleanField()
    note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at', 'pk']


class RequisitionFulfilment(AppendOnlyModel):
    """One actual dispatched bag, counted once; dispatch execution belongs to #37."""
    requisition = models.ForeignKey(Requisition, on_delete=models.PROTECT, related_name='fulfilments')
    blood_unit = models.OneToOneField('inventory.BloodUnit', on_delete=models.PROTECT, related_name='requisition_fulfilment')
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    recorded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['recorded_at', 'pk']
