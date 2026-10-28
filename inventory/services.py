"""
Inventory services for Blood Bank Management System (BBMS).
Provides business logic, aggregation routines, and filtering for blood unit inventory.

SRS References:
- Section 4.7 (BBMS-F-022, BBMS-F-023): Blood Group Management
- Section 4.8, 4.9 (BBMS-F-024 to BBMS-F-030): Serology & Quarantine Exclusion
- Section 4.11 (BBMS-F-033 to BBMS-F-036): Blood Inventory Management (Counts by Group & Location)
- Section 4.12 (BBMS-F-037 to BBMS-F-039): Expiry Handling & FEFO
"""
from datetime import timedelta
from django.core.exceptions import ValidationError
from django.db import IntegrityError, OperationalError, transaction
from django.db.models import Count, Q
from django.utils import timezone

from core.constants import (
    BloodGroup, VALID_BLOOD_GROUPS, get_compatible_donor_groups, is_blood_compatible
)
from requisitions.models import Requisition
from requisitions.services import require_staff
from .models import (
    Allocation, AllocationStatus, BloodUnit, BloodUnitStatus,
    ComponentType, CrossMatchOutcome, DispatchManifest
)


class AllocationConflict(ValidationError):
    """A competing or repeated allocation/dispatch operation needs a fresh copy of the record."""


def get_active_locations():
    """
    Returns a sorted list of unique blood bank location names from both
    BloodBankLocation registry (if available) and existing BloodUnit records.
    SRS BBMS-F-033.
    """
    locations = set()
    try:
        from appointments.models import BloodBankLocation
        db_locations = BloodBankLocation.objects.filter(is_active=True).values_list('name', flat=True)
        locations.update(db_locations)
    except Exception:
        pass

    unit_locations = BloodUnit.objects.exclude(
        location__isnull=True
    ).exclude(
        location__exact=''
    ).values_list('location', flat=True).distinct()
    locations.update(unit_locations)

    if not locations:
        locations.add('Central Blood Bank')

    return sorted(list(locations))


def get_inventory_counts(location=None):
    """
    Calculates real-time blood inventory counts grouped by ABO/Rh blood groups,
    components, and locations. Guarantees that Quarantined, Discarded, and Expired
    units are strictly excluded from available counts.

    SRS BBMS-F-028, BBMS-F-033, BBMS-F-034, BBMS-F-036, BBMS-F-039.
    """
    now = timezone.now()
    soon_threshold = now + timedelta(days=7)

    # Base querysets
    # available() excludes Quarantined, Discarded, and Expired units (SRS BBMS-F-028, BBMS-F-039)
    available_qs = BloodUnit.objects.available()
    quarantined_qs = BloodUnit.objects.quarantined()
    discarded_qs = BloodUnit.objects.discarded()

    if location and location != 'ALL':
        available_qs = available_qs.filter(location__iexact=location)
        quarantined_qs = quarantined_qs.filter(location__iexact=location)
        discarded_qs = discarded_qs.filter(location__iexact=location)

    total_available = available_qs.count()
    total_quarantined = quarantined_qs.count()
    total_discarded = discarded_qs.count()

    # Expiring soon: available units with expiry <= now + 7 days
    expiring_soon_count = available_qs.filter(
        expiry_date__lte=soon_threshold,
        expiry_date__gt=now
    ).count()

    # 1. Stock by ABO/Rh blood group and component type
    group_comp_counts = available_qs.values(
        'blood_group', 'component_type'
    ).annotate(total=Count('id'))

    comp_lookup = {(r['blood_group'], r['component_type']): r['total'] for r in group_comp_counts}

    stock_matrix = []
    grand_component_totals = {
        'whole_blood': 0,
        'rbc': 0,
        'platelets': 0,
        'plasma': 0,
        'total': 0,
    }

    for bg_val, bg_label in BloodGroup.choices:
        wb = comp_lookup.get((bg_val, ComponentType.WHOLE_BLOOD), 0)
        rbc = comp_lookup.get((bg_val, ComponentType.RBC), 0)
        plt = comp_lookup.get((bg_val, ComponentType.PLATELETS), 0)
        ffp = comp_lookup.get((bg_val, ComponentType.PLASMA), 0)
        total_bg = wb + rbc + plt + ffp

        stock_matrix.append({
            'blood_group': bg_val,
            'whole_blood': wb,
            'rbc': rbc,
            'platelets': plt,
            'plasma': ffp,
            'total': total_bg,
        })

        grand_component_totals['whole_blood'] += wb
        grand_component_totals['rbc'] += rbc
        grand_component_totals['platelets'] += plt
        grand_component_totals['plasma'] += ffp
        grand_component_totals['total'] += total_bg

    # 2. Available blood-unit counts grouped by blood group and location (SRS BBMS-F-033, Issue #13)
    # Perform database grouping for optimal performance
    loc_bg_counts = available_qs.values('location', 'blood_group').annotate(total=Count('id'))
    loc_bg_lookup = {(r['location'], r['blood_group']): r['total'] for r in loc_bg_counts}

    # Distinct locations to display
    active_locations = get_active_locations()
    # Also include any locations present in available_qs
    for r in loc_bg_counts:
        if r['location'] and r['location'] not in active_locations:
            active_locations.append(r['location'])
    active_locations = sorted(list(set(active_locations)))

    location_matrix = []
    loc_grand_totals = {bg: 0 for bg in VALID_BLOOD_GROUPS}
    loc_grand_totals['all'] = 0

    for loc_name in active_locations:
        loc_row = {
            'location': loc_name,
            'counts': {},
            'group_counts': [],
            'total': 0,
        }
        for bg in VALID_BLOOD_GROUPS:
            cnt = loc_bg_lookup.get((loc_name, bg), 0)
            loc_row['counts'][bg] = cnt
            loc_row['group_counts'].append({
                'blood_group': bg,
                'count': cnt,
            })
            loc_row['total'] += cnt
            loc_grand_totals[bg] += cnt
            loc_grand_totals['all'] += cnt
        location_matrix.append(loc_row)

    loc_grand_totals_list = [
        {'blood_group': bg, 'total': loc_grand_totals[bg]}
        for bg in VALID_BLOOD_GROUPS
    ]

    return {
        'total_units_available': total_available,
        'quarantined_units': total_quarantined,
        'discarded_units': total_discarded,
        'expiring_soon_count': expiring_soon_count,
        'stock_matrix': stock_matrix,
        'grand_component_totals': grand_component_totals,
        'location_matrix': location_matrix,
        'loc_grand_totals': loc_grand_totals,
        'loc_grand_totals_list': loc_grand_totals_list,
        'active_locations': active_locations,
        'blood_groups': VALID_BLOOD_GROUPS,
    }


def filter_and_search_inventory(
    queryset=None,
    blood_group=None,
    status=None,
    location=None,
    component_type=None,
    search_query=None
):
    """
    Applies filters (blood group, status, location, component) and full-text search
    (bag ID, donor username/name/email, location) on the blood unit inventory.

    SRS References:
    - BBMS-F-020, BBMS-F-021: Bag ID search
    - BBMS-F-022, BBMS-F-034: Blood group and status filter
    - BBMS-F-033: Location filter
    - BBMS-NF-001: Query optimization for sub-2-second response times
    """
    if queryset is None:
        queryset = BloodUnit.objects.select_related(
            'donor', 'collected_by', 'lab_confirmed_by'
        ).order_by('-collection_date')

    # Blood group filter (handles both normal 'A+' and decoded query string '+' as space)
    if blood_group:
        bg_candidate = blood_group.strip().upper()
        if bg_candidate not in VALID_BLOOD_GROUPS and blood_group.endswith(' '):
            bg_candidate = f"{blood_group.strip().upper()}+"
        if bg_candidate in VALID_BLOOD_GROUPS:
            queryset = queryset.filter(blood_group=bg_candidate)

    # Status filter
    if status and status.strip() in BloodUnitStatus.values:
        queryset = queryset.filter(status=status.strip())

    # Location filter
    if location and location.strip() and location.strip().upper() != 'ALL':
        queryset = queryset.filter(location__iexact=location.strip())

    # Component type filter
    if component_type and component_type.strip() in ComponentType.values:
        queryset = queryset.filter(component_type=component_type.strip())

    # Text search
    if search_query and search_query.strip():
        q = search_query.strip()
        queryset = queryset.filter(
            Q(bag_id__icontains=q) |
            Q(donor__username__icontains=q) |
            Q(donor__first_name__icontains=q) |
            Q(donor__last_name__icontains=q) |
            Q(donor__email__icontains=q) |
            Q(location__icontains=q) |
            Q(collection_notes__icontains=q)
        )

    return queryset


def get_fefo_allocation_suggestions(requisition, limit=None):
    """
    Suggest matching safe Available unexpired stock ordered by expiry (FEFO)
    with deterministic tie breaking (SRS BBMS-F-038, BBMS-F-052).
    """
    if isinstance(requisition, (int, str)):
        requisition = Requisition.objects.get(pk=requisition)

    if requisition.status not in (Requisition.Status.APPROVED, Requisition.Status.PARTIALLY_FULFILLED):
        return []

    # Calculate remaining unreserved units required
    current_reserved = requisition.allocations.filter(status=AllocationStatus.RESERVED).count()
    remaining = requisition.quantity - requisition.dispatched_quantity - current_reserved
    if remaining <= 0:
        return []

    target_limit = limit if limit is not None else remaining
    if target_limit <= 0:
        return []

    now = timezone.now()
    compatible_groups = get_compatible_donor_groups(requisition.blood_group)

    # Base queryset for available, unexpired units of the correct component
    qs = BloodUnit.objects.filter(
        component_type=requisition.component_type,
        status=BloodUnitStatus.AVAILABLE,
        expiry_date__gt=now,
        blood_group__in=compatible_groups,
    ).exclude(
        allocations__status=AllocationStatus.RESERVED
    )

    # Deterministic FEFO ordering: earliest expiry first, then collection date, then bag_id
    qs = qs.order_by('expiry_date', 'collection_date', 'bag_id')

    # Ensure all suggested units have passed serology (BBMS-F-024)
    suggested = []
    for unit in qs.prefetch_related('serology_tests'):
        if unit.has_passed_serology:
            suggested.append(unit)
            if len(suggested) >= target_limit:
                break

    return suggested


def get_available_units_for_requisition(requisition):
    """
    Returns available unexpired safe units for this requisition's component,
    annotating each with compatibility status and sorting with compatible
    units first in FEFO order, followed by incompatible units in FEFO order.
    SRS BBMS-F-038, BBMS-F-049, BBMS-F-050.
    """
    if isinstance(requisition, (int, str)):
        requisition = Requisition.objects.get(pk=requisition)

    now = timezone.now()
    qs = BloodUnit.objects.filter(
        component_type=requisition.component_type,
        status=BloodUnitStatus.AVAILABLE,
        expiry_date__gt=now,
    ).exclude(
        allocations__status=AllocationStatus.RESERVED
    ).order_by('expiry_date', 'collection_date', 'bag_id').prefetch_related('serology_tests')

    compatible_groups = set(get_compatible_donor_groups(requisition.blood_group))
    units_info = []
    for unit in qs:
        if unit.has_passed_serology:
            is_compat = unit.blood_group in compatible_groups
            units_info.append({
                'unit': unit,
                'is_compatible': is_compat,
                'cross_match_display': 'Compatible' if is_compat else 'Incompatible',
            })

    # Sort: compatible first, then FEFO order preserved
    units_info.sort(key=lambda x: (not x['is_compatible'], x['unit'].expiry_date))
    return units_info


def allocate_units_to_requisition(*, requisition_pk, unit_ids, actor, override_reason='', expected_version=None):
    """
    Atomically allocate safe available blood units by Bag ID to an approved requisition.
    Supports ABO/Rh compatibility validation and clinical override with justification.
    SRS BBMS-F-035, BBMS-F-038, BBMS-F-050, BBMS-F-051, BBMS-F-052.
    """
    actor = require_staff(actor)
    unit_ids = list(unit_ids)
    if not unit_ids or any(type(pk) is not int for pk in unit_ids) or len(set(unit_ids)) != len(unit_ids):
        raise ValidationError('Select distinct, persisted Bag IDs for allocation.')

    override_reason = (override_reason or '').strip()

    try:
        with transaction.atomic():
            requisition = Requisition.objects.get(pk=requisition_pk)

            if requisition.status not in (Requisition.Status.APPROVED, Requisition.Status.PARTIALLY_FULFILLED):
                raise AllocationConflict('Allocation requires an approved or partially fulfilled requisition.')

            if expected_version is not None and requisition.version != expected_version:
                raise AllocationConflict('This requisition changed. Refresh before submitting again.')

            # Check capacity / over-allocation
            current_reserved = requisition.allocations.filter(status=AllocationStatus.RESERVED).count()
            available_to_reserve = requisition.remaining_quantity - current_reserved
            if len(unit_ids) > available_to_reserve:
                raise ValidationError(
                    f'Cannot allocate {len(unit_ids)} units; only {available_to_reserve} remaining units can be reserved.'
                )

            # Lock / retrieve units
            units = list(
                BloodUnit.objects.filter(pk__in=unit_ids)
                .select_for_update()
                .prefetch_related('serology_tests')
            )
            if len(units) != len(unit_ids):
                raise ValidationError('One or more selected units could not be found.')

            now = timezone.now()
            allocations_created = []

            for unit in units:
                if unit.status != BloodUnitStatus.AVAILABLE:
                    raise ValidationError(
                        f'Unit {unit.bag_id} cannot be allocated: current status is {unit.status}.'
                    )

                if not unit.expiry_date or unit.expiry_date <= now:
                    raise ValidationError(
                        f'Unit {unit.bag_id} cannot be allocated: unit expired on {unit.expiry_date}.'
                    )

                if unit.component_type != requisition.component_type:
                    raise ValidationError(
                        f'Unit {unit.bag_id} component ({unit.component_type}) does not match '
                        f'requisition ({requisition.component_type}).'
                    )

                if not unit.has_passed_serology:
                    raise ValidationError(
                        f'Unit {unit.bag_id} cannot be allocated: has not passed mandatory serology testing.'
                    )

                # Check if unit already has an active reservation
                if Allocation.objects.filter(blood_unit=unit, status=AllocationStatus.RESERVED).exists():
                    raise AllocationConflict(
                        f'Unit {unit.bag_id} is already reserved for an active requisition.'
                    )

                # Check compatibility
                compatible = is_blood_compatible(unit.blood_group, requisition.blood_group)
                if not compatible:
                    if not override_reason:
                        raise ValidationError(
                            f'Unit {unit.bag_id} ({unit.blood_group}) is not compatible with requested group '
                            f'{requisition.blood_group}. An authorized override justification is required.'
                        )
                    outcome = CrossMatchOutcome.OVERRIDDEN
                else:
                    outcome = CrossMatchOutcome.COMPATIBLE

                # Transition unit status to Allocated (SRS BBMS-F-035: automatically decrements available count)
                unit.status = BloodUnitStatus.ALLOCATED
                unit.save(
                    actor=actor,
                    status_reason=f'Allocated to requisition {requisition.requisition_id}. Cross-match: {outcome}.'
                )

                # Persist allocation record
                alloc = Allocation.objects.create(
                    requisition=requisition,
                    blood_unit=unit,
                    cross_match_outcome=outcome,
                    override_reason=override_reason if outcome == CrossMatchOutcome.OVERRIDDEN else '',
                    allocated_by=actor,
                    status=AllocationStatus.RESERVED,
                )
                allocations_created.append(alloc)

            return allocations_created

    except OperationalError as exc:
        if 'locked' not in str(exc).lower():
            raise
        raise AllocationConflict('Database is locked by another update. Refresh and retry.') from exc
    except IntegrityError as exc:
        raise AllocationConflict('Allocation conflicts with another concurrent change. Refresh and retry.') from exc


def cancel_reservation(allocation_pk, *, actor, reason=''):
    """
    Releases an active reservation and returns the unit to Available (if unexpired).
    """
    actor = require_staff(actor)
    reason = (reason or '').strip()

    try:
        with transaction.atomic():
            allocation = Allocation.objects.select_for_update().get(pk=allocation_pk)
            if allocation.status != AllocationStatus.RESERVED:
                raise ValidationError(f'Only Reserved allocations can be cancelled (current: {allocation.status}).')

            unit = allocation.blood_unit
            now = timezone.now()

            # Return unit to Available if unexpired, or Expired if past expiry
            if unit.expiry_date and unit.expiry_date <= now:
                unit.status = BloodUnitStatus.EXPIRED
                unit.save(actor=actor, status_reason=f'Reservation cancelled; unit has expired ({reason}).')
            else:
                unit.status = BloodUnitStatus.AVAILABLE
                unit.save(actor=actor, status_reason=f'Reservation cancelled: {reason or "Released by staff"}.')

            allocation.status = AllocationStatus.CANCELLED
            allocation.cancelled_at = now
            allocation.cancelled_by = actor
            allocation.cancellation_reason = reason
            allocation.save(update_fields=['status', 'cancelled_at', 'cancelled_by', 'cancellation_reason'])

            return allocation

    except OperationalError as exc:
        if 'locked' not in str(exc).lower():
            raise
        raise AllocationConflict('Database is locked. Refresh and retry.') from exc

