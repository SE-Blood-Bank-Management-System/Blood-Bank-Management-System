"""Request transitions shared by HTML/JSON and the future allocation/dispatch app."""
from functools import wraps

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, OperationalError, transaction
from django.db.models import Count, F
from django.utils import timezone

from accounts.models import User
from inventory.models import BloodUnit, BloodUnitStatus
from .compatibility import (
    explain_compatibility,
    get_compatible_donor_groups,
    is_transfusion_compatible,
)
from .models import (
    CrossMatchDecision,
    CrossMatchOutcome,
    DeliveryConfirmation,
    Requisition,
    RequisitionEvent,
    RequisitionFulfilment,
)


class RequisitionConflict(ValidationError):
    """A competing or repeated transition needs a fresh copy of the request."""


def active_actor(actor):
    if not getattr(actor, 'is_authenticated', False) or not actor.pk:
        raise PermissionDenied('Authentication required.')
    current = User.objects.filter(pk=actor.pk, is_active=True).first()
    if current is None or (current.is_hospital and not current.is_approved):
        raise PermissionDenied('An active, approved account is required.')
    return current


def require_staff(actor):
    actor = active_actor(actor)
    # Django admin's is_staff flag alone does not grant a BBMS clinical role.
    if actor.role not in (User.Role.STAFF, User.Role.ADMIN) and not actor.is_superuser:
        raise PermissionDenied('Only blood-bank staff may review requisitions.')
    return actor


def require_hospital(actor):
    actor = active_actor(actor)
    if actor.role != User.Role.HOSPITAL:
        raise PermissionDenied('Only an approved hospital may submit requisitions.')
    return actor


def visible_requisitions(actor):
    actor = active_actor(actor)
    queryset = Requisition.objects.select_related('hospital', 'reviewed_by').annotate(
        _dispatched_quantity=Count('fulfilments'),
    )
    if actor.role == User.Role.HOSPITAL:
        return queryset.filter(hospital=actor).order_by('-created_at', '-pk')
    require_staff(actor)
    return queryset.order_by('-is_stat', 'created_at', 'pk')


def atomic_mutation(func):
    @wraps(func)
    def wrapped(*args, **kwargs):
        try:
            with transaction.atomic():
                return func(*args, **kwargs)
        except OperationalError as exc:
            if 'locked' not in str(exc).lower():
                raise
            raise RequisitionConflict('Another update is in progress. Refresh and retry.') from exc
        except IntegrityError as exc:
            raise RequisitionConflict('This change conflicts with another recorded update. Refresh and retry.') from exc
    return wrapped


def _event(requisition, actor, action, previous_status='', previous_is_stat=None, note=''):
    return RequisitionEvent.objects.create(
        requisition=requisition, actor=actor, actor_label=actor.username, action=action,
        previous_status=previous_status, new_status=requisition.status,
        previous_is_stat=previous_is_stat, new_is_stat=requisition.is_stat, note=note,
    )


def _check_version(requisition, expected_version):
    if expected_version is not None:
        if type(expected_version) is not int or expected_version < 0:
            raise ValidationError('Version must be a non-negative integer.')
        if requisition.version != expected_version:
            raise RequisitionConflict('This requisition changed. Refresh before submitting again.')


def _claim(requisition, expected_version=None):
    _check_version(requisition, expected_version)
    # SQLite has no SELECT FOR UPDATE row locks; the conditional write claims a version.
    changed = Requisition.objects.filter(pk=requisition.pk, version=requisition.version).update(version=F('version') + 1)
    if not changed:
        raise RequisitionConflict('This requisition changed. Refresh and retry.')
    requisition.version += 1


@atomic_mutation
def submit_requisition(*, actor, blood_group, component_type, quantity, required_by, is_stat=False):
    actor = require_hospital(actor)
    if type(quantity) is not int or quantity < 1:
        raise ValidationError({'quantity': 'Enter a positive whole number of units.'})
    if type(is_stat) is not bool:
        raise ValidationError({'is_stat': 'Use true or false for emergency priority.'})
    requisition = Requisition(
        hospital=actor, blood_group=blood_group, component_type=component_type,
        quantity=quantity, required_by=required_by, is_stat=is_stat,
    )
    requisition.full_clean()
    if requisition.required_by < timezone.localdate():
        raise ValidationError({'required_by': 'Required-by date cannot be in the past.'})
    requisition.save()
    _event(requisition, actor, RequisitionEvent.Action.SUBMITTED)
    return requisition


@atomic_mutation
def review_requisition(requisition_pk, *, actor, action, reason='', expected_version=None):
    actor = require_staff(actor)
    if action not in ('approve', 'reject'):
        raise ValidationError('Choose approve or reject. Fulfilment is recorded by dispatch.')
    if not isinstance(reason, str):
        raise ValidationError({'reason': 'Enter a text explanation.'})
    reason = reason.strip()
    if action == 'reject' and not reason:
        raise ValidationError({'reason': 'A rejection reason is required.'})
    requisition = Requisition.objects.get(pk=requisition_pk)
    if requisition.status != Requisition.Status.PENDING:
        raise RequisitionConflict('Only a Pending requisition can be reviewed.')
    _claim(requisition, expected_version)
    previous = requisition.status
    requisition.status = Requisition.Status.APPROVED if action == 'approve' else Requisition.Status.REJECTED
    requisition.rejection_reason = reason if action == 'reject' else ''
    requisition.reviewed_by = actor
    requisition.reviewed_at = timezone.now()
    requisition.save(update_fields=['status', 'rejection_reason', 'reviewed_by', 'reviewed_at', 'updated_at'])
    event_action = RequisitionEvent.Action.APPROVED if action == 'approve' else RequisitionEvent.Action.REJECTED
    _event(requisition, actor, event_action, previous, requisition.is_stat, reason)
    return requisition


@atomic_mutation
def set_priority(requisition_pk, *, actor, is_stat, expected_version=None):
    actor = require_hospital(actor)
    if type(is_stat) is not bool:
        raise ValidationError({'is_stat': 'Use true or false for emergency priority.'})
    requisition = Requisition.objects.get(pk=requisition_pk)
    if requisition.hospital_id != actor.pk:
        raise PermissionDenied('This requisition belongs to another hospital.')
    if requisition.status != Requisition.Status.PENDING:
        raise RequisitionConflict('Only Pending requisitions can change priority.')
    _check_version(requisition, expected_version)
    if requisition.is_stat == is_stat:
        return requisition
    _claim(requisition, expected_version)
    previous = requisition.is_stat
    requisition.is_stat = is_stat
    requisition.save(update_fields=['is_stat', 'updated_at'])
    _event(requisition, actor, RequisitionEvent.Action.PRIORITY_CHANGED, requisition.status, previous)
    return requisition


@atomic_mutation
def record_dispatched_units(requisition_pk, *, actor, unit_ids, expected_version=None):
    """Internal #37 integration hook, called inside its validated dispatch transaction.

    This records evidence, not an allocation/dispatch operation or an HTTP endpoint.
    The dispatch service owns compatibility/override and reservation checks.
    """
    actor = require_staff(actor)
    unit_ids = list(unit_ids)
    if not unit_ids or any(type(pk) is not int for pk in unit_ids) or len(set(unit_ids)) != len(unit_ids):
        raise ValidationError('Select distinct, persisted dispatched Bag IDs.')
    requisition = Requisition.objects.get(pk=requisition_pk)
    if requisition.status not in (Requisition.Status.APPROVED, Requisition.Status.PARTIALLY_FULFILLED):
        raise RequisitionConflict('Dispatch requires an approved, incompletely fulfilled requisition.')
    _claim(requisition, expected_version)
    units = list(BloodUnit.objects.filter(pk__in=unit_ids))
    now = timezone.now()
    if len(units) != len(unit_ids) or any(
        unit.status != BloodUnitStatus.DISPATCHED or unit.component_type != requisition.component_type
        or not unit.expiry_date or unit.expiry_date <= now or not unit.has_passed_serology for unit in units
    ):
        raise ValidationError('Every selected unit must already be Dispatched, unexpired and the requested component.')
    if RequisitionFulfilment.objects.filter(blood_unit_id__in=unit_ids).exists():
        raise RequisitionConflict('A selected Bag ID is already counted against a requisition.')
    count = requisition.dispatched_quantity + len(units)
    if count > requisition.quantity:
        raise ValidationError('Dispatched units exceed the remaining requested quantity.')
    RequisitionFulfilment.objects.bulk_create([
        RequisitionFulfilment(requisition=requisition, blood_unit=unit, recorded_by=actor) for unit in units
    ])
    previous = requisition.status
    requisition.status = (Requisition.Status.FULFILLED if count == requisition.quantity
                          else Requisition.Status.PARTIALLY_FULFILLED)
    requisition.save(update_fields=['status', 'updated_at'])
    _event(requisition, actor, RequisitionEvent.Action.DISPATCH_RECORDED, previous, requisition.is_stat,
           'Dispatched Bag IDs: ' + ', '.join(unit.bag_id for unit in units))
    return requisition


@atomic_mutation
def confirm_receipt(requisition_pk, *, actor, bag_ids, expected_version=None):
    """Acknowledge actual dispatched bags; fulfilment remains dispatch-based."""
    actor = require_hospital(actor)
    if (not isinstance(bag_ids, list) or not bag_ids
            or any(not isinstance(bag, str) or not bag.strip() for bag in bag_ids)
            or len(set(bag_ids)) != len(bag_ids)):
        raise ValidationError('Select distinct dispatched Bag IDs.')
    requisition = Requisition.objects.get(pk=requisition_pk)
    if requisition.hospital_id != actor.pk:
        raise PermissionDenied('This requisition belongs to another hospital.')
    _claim(requisition, expected_version)
    fulfilments = list(RequisitionFulfilment.objects.filter(
        requisition=requisition, blood_unit__bag_id__in=bag_ids,
    ).select_related('blood_unit').order_by('blood_unit_id'))
    if len(fulfilments) != len(bag_ids):
        raise ValidationError('Every Bag ID must have been dispatched against this requisition.')
    if DeliveryConfirmation.objects.filter(fulfilment__in=fulfilments).exists():
        raise RequisitionConflict('A selected bag already has a receipt confirmation.')
    # Lock current units rather than relying on a stale joined status.
    units = {unit.pk: unit for unit in BloodUnit.objects.select_for_update().filter(
        pk__in=[item.blood_unit_id for item in fulfilments],
    ).order_by('pk')}
    if any(unit.status != BloodUnitStatus.DISPATCHED for unit in units.values()):
        raise RequisitionConflict('Only Dispatched units can be confirmed as received.')
    for item in fulfilments:
        DeliveryConfirmation.objects.create(
            fulfilment=item, received_by=actor, receiver_label=actor.username,
        )
        unit = units[item.blood_unit_id]
        unit.status = BloodUnitStatus.DELIVERED
        unit.save(actor=actor, status_reason=f'Hospital receipt confirmed for {requisition.requisition_id}.')
    requisition.save(update_fields=['updated_at'])
    _event(requisition, actor, RequisitionEvent.Action.RECEIPT_CONFIRMED,
           requisition.status, requisition.is_stat, 'Received Bag IDs: ' + ', '.join(bag_ids))
    return requisition


def pending_stat_summary(actor):
    require_staff(actor)
    pending = Requisition.objects.filter(status=Requisition.Status.PENDING, is_stat=True)
    latest = pending.order_by('-updated_at', '-pk').first()
    return {'count': pending.count(), 'latest_id': latest.requisition_id if latest else None,
            'latest_updated_at': latest.updated_at.isoformat() if latest else None}


def evaluate_unit_for_requisition(requisition, blood_unit):
    """
    Evaluates unit safety, availability, and biological compatibility against a requisition.
    SRS BBMS-F-049, BBMS-F-050.
    """
    now = timezone.now()
    safety_errors = []

    if blood_unit.status != BloodUnitStatus.AVAILABLE:
        safety_errors.append(f"Unit is '{blood_unit.status}', not Available (SRS BBMS-F-028).")
    if blood_unit.expiry_date and blood_unit.expiry_date <= now:
        safety_errors.append("Unit has passed shelf-life and is expired (SRS BBMS-F-039).")
    if not blood_unit.has_passed_serology:
        safety_errors.append("Unit has not passed all four required serology screening tests (SRS BBMS-F-024).")
    if blood_unit.component_type != requisition.component_type:
        safety_errors.append(
            f"Component mismatch: unit is '{blood_unit.component_type}', requested is '{requisition.component_type}'."
        )
    if hasattr(blood_unit, 'requisition_fulfilment'):
        safety_errors.append("Unit is already allocated or dispatched to another requisition.")

    is_compat = is_transfusion_compatible(
        blood_unit.blood_group, requisition.blood_group, requisition.component_type
    )
    explanation = explain_compatibility(
        blood_unit.blood_group, requisition.blood_group, requisition.component_type
    )

    return {
        'is_safe': len(safety_errors) == 0,
        'safety_errors': safety_errors,
        'is_compatible': is_compat,
        'explanation': explanation,
        'requested_blood_group': requisition.blood_group,
        'donor_blood_group': blood_unit.blood_group,
        'component_type': requisition.component_type,
    }


@atomic_mutation
def record_cross_match(requisition_pk, unit_identifier, *, actor, override_reason='', notes='', expected_version=None):
    """
    Evaluates cross-matching between a blood unit and requisition and records an auditable decision.
    SRS References:
    - BBMS-F-049: ABO/Rh transfusion compatibility check.
    - BBMS-F-050: Incompatible units blocked unless explicit authorized override recorded.
    - BBMS-F-051: Cross-match outcome recorded (Compatible / Incompatible / Overridden).
    - BBMS-SR-003, BBMS-SR-004: Staff authorization and non-repudiation.

    unit_identifier: BloodUnit pk (int) or bag_id (str) or BloodUnit instance.
    """
    actor = require_staff(actor)
    requisition = Requisition.objects.get(pk=requisition_pk)

    if requisition.status not in (Requisition.Status.APPROVED, Requisition.Status.PARTIALLY_FULFILLED):
        raise ValidationError('Cross-matching and allocation can only be performed on approved requisitions.')

    # Resolve blood unit
    if isinstance(unit_identifier, BloodUnit):
        unit = unit_identifier
    elif isinstance(unit_identifier, int) or (isinstance(unit_identifier, str) and unit_identifier.isdigit()):
        unit = BloodUnit.objects.filter(pk=int(unit_identifier)).first()
    else:
        unit = BloodUnit.objects.filter(bag_id=str(unit_identifier).strip()).first()

    if not unit:
        raise ValidationError(f"Blood unit '{unit_identifier}' does not exist.")

    # Safety checks: Overrides NEVER bypass expiry, serology, component, or status safety!
    evaluation = evaluate_unit_for_requisition(requisition, unit)
    if not evaluation['is_safe']:
        raise ValidationError(
            f"Cannot cross-match or allocate unit {unit.bag_id}: {'; '.join(evaluation['safety_errors'])}"
        )

    is_compat = evaluation['is_compatible']
    explanation = evaluation['explanation']
    override_reason_clean = str(override_reason or '').strip()

    if not is_compat:
        if not override_reason_clean:
            raise ValidationError(
                f"Unit {unit.bag_id} ({unit.blood_group}) is biologically INCOMPATIBLE with "
                f"requisition blood group {requisition.blood_group} for {requisition.component_type}. "
                f"Transfusion is blocked unless an authorized staff member supplies an explicit "
                f"override justification (SRS BBMS-F-050)."
            )
        outcome = CrossMatchOutcome.OVERRIDDEN
        is_overridden = True
    else:
        outcome = CrossMatchOutcome.COMPATIBLE
        is_overridden = False

    decision = CrossMatchDecision.objects.create(
        requisition=requisition,
        blood_unit=unit,
        requested_blood_group=requisition.blood_group,
        donor_blood_group=unit.blood_group,
        component_type=requisition.component_type,
        outcome=outcome,
        is_compatible=is_compat,
        is_overridden=is_overridden,
        override_reason=override_reason_clean if is_overridden else '',
        performed_by=actor,
        performed_by_label=actor.username,
        explanation=explanation,
    )

    event_note = f"Cross-match for unit {unit.bag_id} ({unit.blood_group} -> {requisition.blood_group}): {outcome}."
    if is_overridden:
        event_note += f" Override justification: {override_reason_clean}"
    _event(
        requisition, actor, RequisitionEvent.Action.CROSS_MATCH_RECORDED,
        requisition.status, requisition.is_stat, event_note
    )

    return decision


def get_compatible_inventory_for_requisition(requisition):
    """
    Returns available units matching the requisition's component type and compatible
    blood groups, ordered in First-Expiry-First-Out (FEFO) sequence (SRS BBMS-F-035, BBMS-F-049).
    Excludes units that have already been fulfilled/allocated to requisitions.
    """
    compatible_groups = get_compatible_donor_groups(
        requisition.blood_group, requisition.component_type
    )

    qs = BloodUnit.objects.available().filter(
        component_type=requisition.component_type,
        blood_group__in=compatible_groups,
    ).exclude(
        requisition_fulfilment__isnull=False
    ).order_by('expiry_date', 'collection_date', 'pk')

    return qs
