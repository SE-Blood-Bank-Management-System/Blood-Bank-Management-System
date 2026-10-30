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
    # Shared BloodGroup choices (SRS BBMS-F-022, Issue #43)
    blood_group = models.CharField(max_length=5, choices=BloodGroup.choices)
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
    def bulk_create(self, objs, batch_size=None, ignore_conflicts=False, update_conflicts=False,
                    update_fields=None, unique_fields=None):
        if ignore_conflicts or update_conflicts:
            raise ValidationError('Requisition history conflicts must not be ignored or overwritten.')
        return super().bulk_create(objs, batch_size=batch_size)

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
        if not self._state.adding or (self.pk is not None and type(self).objects.filter(pk=self.pk).exists()):
            raise ValidationError('Requisition history is append-only.')
        kwargs['force_insert'] = True
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError('Requisition history cannot be deleted.')


class CrossMatchOutcome(models.TextChoices):
    """
    Cross-matching outcome classifications (SRS BBMS-F-051).
    """
    COMPATIBLE = 'Compatible', 'Compatible'
    INCOMPATIBLE = 'Incompatible', 'Incompatible'
    OVERRIDDEN = 'Overridden', 'Overridden'


class RequisitionEvent(AppendOnlyModel):
    class Action(models.TextChoices):
        SUBMITTED = 'Submitted', 'Submitted'
        APPROVED = 'Approved', 'Approved'
        REJECTED = 'Rejected', 'Rejected'
        PRIORITY_CHANGED = 'Priority changed', 'Priority changed'
        CROSS_MATCH_RECORDED = 'Cross-match recorded', 'Cross-match recorded'
        DISPATCH_RECORDED = 'Dispatch recorded', 'Dispatch recorded'
        RECEIPT_CONFIRMED = 'Receipt confirmed', 'Receipt confirmed'

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


class DeliveryConfirmation(AppendOnlyModel):
    """One hospital custody acknowledgement per dispatched bag (F-056/F-057)."""
    fulfilment = models.OneToOneField(
        RequisitionFulfilment, on_delete=models.PROTECT, related_name='delivery_confirmation',
    )
    received_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    receiver_label = models.CharField(max_length=150)
    received_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['received_at', 'pk']


class CrossMatchDecision(AppendOnlyModel):
    """
    Append-only record of a cross-matching determination and staff override.
    SRS References:
    - BBMS-F-049: ABO/Rh transfusion compatibility determination.
    - BBMS-F-050: Incompatible allocation blocked unless explicit authorized override recorded.
    - BBMS-F-051: Cross-match outcome recorded (Compatible / Incompatible / Overridden).
    - BBMS-SR-004, BBMS-SR-008: Non-repudiation and auditability.
    """
    requisition = models.ForeignKey(
        Requisition, on_delete=models.PROTECT, related_name='cross_matches',
        help_text='Associated hospital blood requisition (SRS BBMS-F-043).'
    )
    blood_unit = models.ForeignKey(
        'inventory.BloodUnit', on_delete=models.PROTECT, related_name='cross_matches',
        help_text='Evaluated blood inventory unit (SRS BBMS-F-020).'
    )
    requested_blood_group = models.CharField(max_length=5)
    donor_blood_group = models.CharField(max_length=5)
    component_type = models.CharField(max_length=30)
    outcome = models.CharField(max_length=20, choices=CrossMatchOutcome.choices)
    is_compatible = models.BooleanField(
        help_text='Biological transfusion compatibility outcome based on standard rules.'
    )
    is_overridden = models.BooleanField(
        default=False,
        help_text='Whether an incompatible match was authorized via staff clinical override.'
    )
    override_reason = models.TextField(
        blank=True,
        help_text='Mandatory clinical rationale provided by staff when overriding incompatibility.'
    )
    performed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        help_text='Staff member who performed the cross-match and authorized override.'
    )
    performed_by_label = models.CharField(max_length=150)
    explanation = models.TextField(
        blank=True,
        help_text='Clinical explanation of compatibility determination.'
    )
    performed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-performed_at', '-pk']
        indexes = [
            models.Index(fields=['requisition', 'performed_at']),
            models.Index(fields=['blood_unit', 'performed_at']),
        ]

    def __str__(self):
        return f"{self.blood_unit.bag_id} -> {self.requisition.requisition_id}: {self.outcome}"

