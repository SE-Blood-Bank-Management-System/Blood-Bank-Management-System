"""
Views for Blood Bank Inventory management.
SRS References:
- Section 4.6 (BBMS-F-020, BBMS-F-021): Unique Blood Unit / Bag ID
- Section 4.7 (BBMS-F-022, BBMS-F-023): Blood Group Management
- Section 4.8, 4.9 (BBMS-F-024 to BBMS-F-030): Quarantine & Testing
- Section 4.11 (BBMS-F-033 to BBMS-F-036): Inventory Management
- Section 4.12 (BBMS-F-037 to BBMS-F-039): Expiry & FEFO
"""
import json
from datetime import timedelta
from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods, require_safe

from accounts.models import User
from accounts.rbac import _is_api_request, role_required
from core.constants import BloodGroup, VALID_BLOOD_GROUPS
from requisitions.models import Requisition
from .forms import (
    AllocationForm,
    BloodCollectionForm,
    BloodGroupCorrectionForm,
    ComponentSeparationForm,
    DispatchForm,
    InventoryFilterForm,
    SerologyPanelForm,
)
from .models import (
    Allocation,
    AllocationStatus,
    BloodUnit,
    BloodUnitStatus,
    ComponentType,
    CrossMatchOutcome,
    DispatchManifest,
    SerologyResult,
    SerologyTestType,
)
from .services import (
    AllocationConflict,
    allocate_units_to_requisition,
    cancel_reservation,
    dispatch_allocated_units,
    filter_and_search_inventory,
    get_active_locations,
    get_available_units_for_requisition,
    get_fefo_allocation_suggestions,
    get_inventory_counts,
    process_expired_units,
)


def _normalize_blood_group(bg_raw):
    """Normalizes blood group strings, handling URL unencoded '+' translated to space."""
    if not bg_raw:
        return ''
    clean = bg_raw.strip().upper()
    if clean in VALID_BLOOD_GROUPS:
        return clean
    if bg_raw.endswith(' ') and f"{clean}+" in VALID_BLOOD_GROUPS:
        return f"{clean}+"
    return clean


def _serialize_blood_unit(unit):
    """Helper to serialize a BloodUnit instance for API responses."""
    return {
        'id': unit.id,
        'bag_id': unit.bag_id,
        'blood_group': unit.blood_group,
        'donor_self_reported_group': unit.donor_self_reported_group,
        'status': unit.status,
        'component_type': unit.component_type,
        'volume_ml': unit.volume_ml,
        'location': unit.location,
        'collection_date': unit.collection_date.isoformat() if unit.collection_date else None,
        'expiry_date': unit.expiry_date.isoformat() if unit.expiry_date else None,
        'is_available': unit.is_available,
        'is_quarantined': unit.is_quarantined,
        'is_discarded': unit.is_discarded,
        'is_expired': unit.is_expired,
        'donor': {
            'id': unit.donor.id,
            'username': unit.donor.username,
            'name': unit.donor.get_full_name() or unit.donor.username,
        } if unit.donor else None,
        'lab_confirmed_by': unit.lab_confirmed_by.username if unit.lab_confirmed_by else None,
        'lab_confirmed_at': unit.lab_confirmed_at.isoformat() if unit.lab_confirmed_at else None,
    }


@role_required(User.Role.STAFF, User.Role.ADMIN)
def inventory_dashboard(request):
    """
    Inventory management dashboard for staff and administrators.
    Displays units grouped by the eight ABO/Rh blood groups, component types,
    locations, and provides searchable, filterable inventory lists.

    SRS References:
    - BBMS-F-020, BBMS-F-021: Unique Bag ID and searching
    - BBMS-F-022, BBMS-F-023: Blood group display and verification
    - BBMS-F-028: Quarantined & Discarded units excluded from available stock counts
    - BBMS-F-033: Real-time available count grouped by blood group and location
    - BBMS-F-034: Filter by blood group, component type, and status
    - BBMS-F-037, BBMS-F-039: Expiry handling & FEFO metrics
    - BBMS-NF-001: Sub-2-second search and filter response time
    """
    if _is_api_request(request):
        return api_inventory(request)

    q = request.GET.get('q', '').strip()
    blood_group = _normalize_blood_group(request.GET.get('blood_group', ''))
    status = request.GET.get('status', '').strip()
    location = request.GET.get('location', '').strip()
    component_type = request.GET.get('component_type', '').strip()

    # Calculate real-time counts across groups, components, and locations
    counts_data = get_inventory_counts(location=location if location else None)
    active_locations = counts_data['active_locations']

    # Filter and search blood units
    filtered_qs = filter_and_search_inventory(
        blood_group=blood_group,
        status=status,
        location=location,
        component_type=component_type,
        search_query=q,
    )

    # Initialize filter form with current parameters and active locations
    filter_form = InventoryFilterForm(
        request.GET or None,
        locations=active_locations,
        initial={
            'q': q,
            'blood_group': blood_group,
            'status': status,
            'location': location,
            'component_type': component_type,
        }
    )

    # Pagination: 15 units per page
    paginator = Paginator(filtered_qs, 15)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    has_active_filters = bool(q or blood_group or status or location or component_type)

    context = {
        'title': 'Blood Inventory Dashboard',
        'blood_groups': VALID_BLOOD_GROUPS,
        'filter_form': filter_form,
        'page_obj': page_obj,
        'recent_units': page_obj.object_list,
        'total_filtered_units': filtered_qs.count(),
        'stock_matrix': counts_data['stock_matrix'],
        'grand_component_totals': counts_data['grand_component_totals'],
        'location_matrix': counts_data['location_matrix'],
        'loc_grand_totals': counts_data['loc_grand_totals'],
        'loc_grand_totals_list': counts_data['loc_grand_totals_list'],
        'total_units_available': counts_data['total_units_available'],
        'quarantined_units': counts_data['quarantined_units'],
        'discarded_units': counts_data['discarded_units'],
        'expiring_soon_count': counts_data['expiring_soon_count'],
        'active_locations': active_locations,
        'selected_filters': {
            'q': q,
            'blood_group': blood_group,
            'status': status,
            'location': location,
            'component_type': component_type,
        },
        'has_active_filters': has_active_filters,
    }
    return render(request, 'inventory/dashboard.html', context)


@role_required(User.Role.STAFF, User.Role.ADMIN)
@require_http_methods(["GET"])
def api_inventory(request):
    """
    Dedicated REST API endpoint for blood inventory listing, counts, and search.
    SAD Section 4.3: GET /api/inventory
    SRS References:
    - BBMS-F-028: Quarantined/Discarded units excluded from available stock counts.
    - BBMS-F-033: Real-time count of available blood units per blood group and location.
    - BBMS-F-034: Filter by blood group, component type, and status.
    - BBMS-NF-001: Sub-2-second query response time.
    """
    q = request.GET.get('q', '').strip()
    blood_group = _normalize_blood_group(request.GET.get('blood_group', ''))
    status = request.GET.get('status', '').strip()
    location = request.GET.get('location', '').strip()
    component_type = request.GET.get('component_type', '').strip()

    counts_data = get_inventory_counts(location=location if location else None)
    filtered_qs = filter_and_search_inventory(
        blood_group=blood_group,
        status=status,
        location=location,
        component_type=component_type,
        search_query=q,
    )

    # Support customizable page size for API clients
    try:
        page_size = min(max(int(request.GET.get('page_size', 20)), 1), 100)
    except (ValueError, TypeError):
        page_size = 20

    paginator = Paginator(filtered_qs, page_size)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)

    return JsonResponse({
        'status': 'success',
        'summary': {
            'total_available': counts_data['total_units_available'],
            'total_quarantined': counts_data['quarantined_units'],
            'total_discarded': counts_data['discarded_units'],
            'expiring_soon_count': counts_data['expiring_soon_count'],
        },
        'by_blood_group': counts_data['stock_matrix'],
        'by_location': counts_data['location_matrix'],
        'active_locations': counts_data['active_locations'],
        'filters': {
            'q': q,
            'blood_group': blood_group,
            'status': status,
            'location': location,
            'component_type': component_type,
        },
        'pagination': {
            'total_count': paginator.count,
            'page': page_obj.number,
            'num_pages': paginator.num_pages,
            'has_next': page_obj.has_next(),
            'has_previous': page_obj.has_previous(),
        },
        'results': [_serialize_blood_unit(u) for u in page_obj.object_list],
    }, status=200)


@role_required(User.Role.STAFF, User.Role.ADMIN)
@never_cache
@require_safe
def quarantine_list(request):
    """
    List units pending serology testing or under quarantine.
    Displays elapsed quarantine time, Bag ID, and lab-confirmed vs self-reported blood group.
    SRS: 4.8, 4.9 (BBMS-F-026 to BBMS-F-030).
    """
    quarantined_qs = BloodUnit.objects.quarantined().select_related(
        'donor', 'lab_confirmed_by',
    ).order_by('quarantined_at', 'collection_date', 'pk')
    page = Paginator(quarantined_qs, 25).get_page(request.GET.get('page'))
    if _is_api_request(request):
        return JsonResponse({
            'count': page.paginator.count, 'page': page.number, 'pages': page.paginator.num_pages,
            'units': [{
                'bag_id': unit.bag_id, 'blood_group': unit.blood_group or None,
                'collection_date': unit.collection_date.isoformat(),
                'quarantined_at': (unit.quarantined_at or unit.collection_date).isoformat(),
                'quarantine_duration_days': unit.quarantine_duration_days,
            } for unit in page],
        })

    context = {
        'title': 'Quarantine & Serology Testing',
        'quarantined_units': page,
        'page_obj': page,
        'quarantine_count': page.paginator.count,
    }
    return render(request, 'inventory/quarantine.html', context)


@role_required(User.Role.STAFF, User.Role.ADMIN)
@never_cache
@require_safe
def status_history(request, bag_id):
    unit = get_object_or_404(BloodUnit, bag_id=bag_id)
    page = Paginator(unit.status_changes.select_related('changed_by'), 25).get_page(request.GET.get('page'))
    if _is_api_request(request):
        return JsonResponse({
            'bag_id': unit.bag_id, 'count': page.paginator.count, 'page': page.number,
            'pages': page.paginator.num_pages,
            'history': [{
                'previous_status': event.previous_status or None, 'new_status': event.new_status,
                'staff_id': event.changed_by_id, 'staff_username': event.actor_label,
                'timestamp': event.changed_at.isoformat(), 'reason': event.reason,
            } for event in page],
            'legacy_notes': unit.status_audit_log,
        })
    return render(request, 'inventory/status_history.html', {'unit': unit, 'page_obj': page})


@role_required(User.Role.STAFF, User.Role.ADMIN)
def blood_unit_detail(request, bag_id):
    """
    Detailed view of a blood unit for authorized staff/admins.
    Highlights the separation between donor self-reported blood group and
    laboratory-confirmed blood group (SRS BBMS-F-022, BBMS-F-023).
    """
    unit = get_object_or_404(
        BloodUnit.objects.select_related('donor', 'lab_confirmed_by', 'parent_unit')
        .prefetch_related('serology_tests'),
        bag_id=bag_id
    )
    form = BloodGroupCorrectionForm(initial={'blood_group': unit.blood_group})
    serology_form = SerologyPanelForm(blood_unit=unit)

    context = {
        'title': f"Blood Unit {unit.bag_id}",
        'unit': unit,
        'form': form,
        'serology_form': serology_form,
    }
    return render(request, 'inventory/unit_detail.html', context)


@role_required(User.Role.STAFF, User.Role.ADMIN)
@require_http_methods(["GET", "POST"])
def update_unit_blood_group(request, bag_id):
    """
    Allows authorized staff to record or correct the laboratory-confirmed
    blood group of a blood unit (SRS BBMS-F-023).
    Supports both HTML form submission and JSON API requests.
    """
    unit = get_object_or_404(
        BloodUnit.objects.select_related('donor', 'lab_confirmed_by'),
        bag_id=bag_id
    )

    if request.method == 'GET':
        return redirect('inventory:unit_detail', bag_id=unit.bag_id)

    # 1. Handle JSON / API request
    if _is_api_request(request) or request.content_type == 'application/json':
        try:
            body = json.loads(request.body.decode('utf-8')) if request.body else {}
        except json.JSONDecodeError:
            return JsonResponse({'error': 'Malformed JSON payload.'}, status=400)

        new_bg = body.get('blood_group')
        notes = body.get('notes', '')

        if not new_bg or str(new_bg).strip().upper() not in VALID_BLOOD_GROUPS:
            return JsonResponse({
                'error': f"Invalid blood group '{new_bg}'. Supported values are: {', '.join(VALID_BLOOD_GROUPS)}."
            }, status=400)

        try:
            unit.update_blood_group(new_bg, staff_user=request.user, notes=notes)
        except ValidationError as e:
            return JsonResponse({'error': str(e)}, status=400)

        return JsonResponse({
            'success': True,
            'message': f"Blood group for unit {unit.bag_id} successfully recorded as {unit.blood_group}.",
            'bag_id': unit.bag_id,
            'blood_group': unit.blood_group,
            'donor_self_reported_group': unit.donor_self_reported_group,
            'lab_confirmed_by': request.user.username,
            'lab_confirmed_at': unit.lab_confirmed_at.isoformat() if unit.lab_confirmed_at else None,
        }, status=200)

    # 2. Handle HTML Form POST
    form = BloodGroupCorrectionForm(request.POST)
    if form.is_valid():
        new_bg = form.cleaned_data['blood_group']
        notes = form.cleaned_data['notes']
        unit.update_blood_group(new_bg, staff_user=request.user, notes=notes)
        messages.success(
            request,
            f"Laboratory-confirmed blood group for unit {unit.bag_id} updated to {unit.blood_group}."
        )
        return redirect('inventory:unit_detail', bag_id=unit.bag_id)
    else:
        context = {
            'title': f"Blood Unit {unit.bag_id}",
            'unit': unit,
            'form': form,
        }
        return render(request, 'inventory/unit_detail.html', context, status=400)


@role_required(User.Role.STAFF, User.Role.ADMIN)
@require_http_methods(["POST", "PATCH"])
def api_update_unit_blood_group(request, bag_id):
    """
    Dedicated REST API endpoint for recording/correcting blood group.
    SAD Section 4.3: PATCH/POST /api/blood-units/{bagId}/blood-group
    SRS BBMS-F-022, BBMS-F-023, BBMS-SR-003.
    """
    return update_unit_blood_group(request, bag_id)


@role_required(User.Role.STAFF, User.Role.ADMIN)
def record_blood_collection(request):
    """
    Interface and endpoint for authorized staff to record completed blood collections.
    SRS BBMS-F-017, BBMS-F-018, BBMS-F-019, BBMS-F-020, BBMS-F-021, BBMS-F-026.
    """
    is_api = _is_api_request(request)

    if request.method == 'POST':
        # Support JSON payload for API callers
        if request.content_type == 'application/json' and request.body:
            try:
                data = json.loads(request.body.decode('utf-8'))
            except json.JSONDecodeError:
                return JsonResponse({'error': 'Malformed JSON payload.'}, status=400)
            form = BloodCollectionForm(data)
        else:
            form = BloodCollectionForm(request.POST)

        if form.is_valid():
            unit = form.save(staff_user=request.user)
            success_msg = f"Blood collection recorded successfully! Generated unique Bag ID: {unit.bag_id}"

            if is_api:
                return JsonResponse({
                    'status': 'success',
                    'message': success_msg,
                    'bag_id': unit.bag_id,
                    'donor_id': unit.donor_id,
                    'donor_username': unit.donor.username if unit.donor else None,
                    'blood_group': unit.blood_group,
                    'component_type': unit.component_type,
                    'volume_ml': unit.volume_ml,
                    'unit_status': unit.status,
                    'collection_date': unit.collection_date.isoformat(),
                    'location': unit.location,
                }, status=201)

            messages.success(request, success_msg)
            return redirect('inventory:unit_detail', bag_id=unit.bag_id)
        else:
            if is_api:
                return JsonResponse({
                    'error': 'Validation failed.',
                    'errors': form.errors.get_json_data()
                }, status=400)
            messages.error(request, "Please correct the errors in the blood collection form.")
    else:
        # Pre-select donor if donor_id passed in query string
        initial_data = {}
        donor_id = request.GET.get('donor_id')
        if donor_id:
            try:
                donor_obj = User.objects.get(pk=donor_id, role=User.Role.DONOR)
                initial_data['donor'] = donor_obj
                if donor_obj.blood_group:
                    initial_data['blood_group'] = donor_obj.blood_group
            except (User.DoesNotExist, ValueError):
                pass
        form = BloodCollectionForm(initial=initial_data)

    recent_collections = BloodUnit.objects.select_related(
        'donor', 'collected_by'
    ).order_by('-collection_date')[:10]
    donor_count = User.objects.filter(role=User.Role.DONOR).count()

    context = {
        'title': 'Record Blood Collection',
        'form': form,
        'recent_collections': recent_collections,
        'donor_count': donor_count,
    }
    return render(request, 'inventory/record_collection.html', context)


@role_required(User.Role.STAFF, User.Role.ADMIN)
@require_http_methods(["GET", "POST"])
def record_serology_tests(request, bag_id):
    """
    Staff view and API endpoint to record serology test outcomes (HIV, Hep B, Hep C, Syphilis)
    and execute automatic quarantine status transitions (SRS BBMS-F-024 to BBMS-F-027).
    """
    unit = get_object_or_404(
        BloodUnit,
        bag_id=bag_id
    )

    if request.method == 'GET':
        return redirect('inventory:unit_detail', bag_id=unit.bag_id)

    is_api = _is_api_request(request) or request.content_type == 'application/json'

    if is_api:
        try:
            body = json.loads(request.body.decode('utf-8')) if request.body else {}
        except json.JSONDecodeError:
            return JsonResponse({'error': 'Malformed JSON payload.'}, status=400)

        # Handle both nested 'tests' dict and top-level test fields
        tests_payload = body.get('tests')
        if not tests_payload or not isinstance(tests_payload, dict):
            tests_payload = {}
            for key, val in body.items():
                if key in ('notes', 'csrfmiddlewaretoken'):
                    continue
                k_clean = str(key).strip()
                k_lower = k_clean.lower()
                if k_lower in ('hiv', 'hiv 1/2'):
                    tests_payload[SerologyTestType.HIV] = val
                elif k_lower in ('hepatitis b', 'hepatitis_b', 'hep_b', 'hbsag'):
                    tests_payload[SerologyTestType.HEPATITIS_B] = val
                elif k_lower in ('hepatitis c', 'hepatitis_c', 'hep_c', 'hcv'):
                    tests_payload[SerologyTestType.HEPATITIS_C] = val
                elif k_lower in ('syphilis', 'vdrl', 'rpr'):
                    tests_payload[SerologyTestType.SYPHILIS] = val
                elif k_clean in SerologyTestType.values:
                    tests_payload[k_clean] = val

        if not tests_payload:
            return JsonResponse({'error': 'No serology test results provided in payload.'}, status=400)

        notes = body.get('notes', '')
        try:
            unit.record_serology_panel(tests_payload, staff_user=request.user, notes=notes)
            unit.refresh_from_db()
        except ValidationError as e:
            return JsonResponse({'error': str(e)}, status=400)

        return JsonResponse({
            'status': 'success',
            'message': f"Serology test results recorded for unit {unit.bag_id}. Current status: {unit.status}.",
            'bag_id': unit.bag_id,
            'unit_status': unit.status,
            'is_available': unit.is_available,
            'is_discarded': unit.is_discarded,
            'is_quarantined': unit.is_quarantined,
            'expiry_date': unit.expiry_date.isoformat() if unit.expiry_date else None,
            'serology_tests': unit.serology_summary,
        }, status=200)

    # HTML Form submission
    form = SerologyPanelForm(request.POST, blood_unit=unit)
    if form.is_valid():
        try:
            form.save(unit, staff_user=request.user)
            unit.refresh_from_db()
            if unit.is_available:
                messages.success(
                    request,
                    f"All serology tests passed! Unit {unit.bag_id} is now Available for use. "
                    f"Expiry set to {unit.expiry_date.strftime('%d %b %Y')} (SRS BBMS-F-026, BBMS-F-037)."
                )
            elif unit.is_discarded:
                messages.warning(
                    request,
                    f"Serology failure recorded! Unit {unit.bag_id} has been marked Discarded and removed "
                    f"from usable inventory (SRS BBMS-F-027, BBMS-F-028)."
                )
            else:
                messages.info(
                    request,
                    f"Serology test results saved for unit {unit.bag_id}. Unit remains Quarantined until all "
                    f"four mandatory tests pass (SRS BBMS-F-024, BBMS-F-026)."
                )
            return redirect('inventory:unit_detail', bag_id=unit.bag_id)
        except ValidationError as e:
            messages.error(request, str(e))
            return redirect('inventory:unit_detail', bag_id=unit.bag_id)
    else:
        messages.error(request, "Please correct the errors in the serology testing form.")
        return redirect('inventory:unit_detail', bag_id=unit.bag_id)


@role_required(User.Role.STAFF, User.Role.ADMIN)
@require_http_methods(["POST"])
def api_record_serology(request, bag_id):
    """
    Dedicated REST API endpoint for recording required serology test results.
    SAD Section 4.3: POST /api/blood-units/{bagId}/serology (Staff role)
    SRS BBMS-F-024 to BBMS-F-027, BBMS-SR-003.
    """
    return record_serology_tests(request, bag_id)


@role_required(User.Role.STAFF, User.Role.ADMIN)
def allocate_requisition_view(request, requisition_pk):
    """
    Staff view for FEFO suggestion review and manual Bag ID allocation
    to an approved requisition.
    SRS BBMS-F-035, BBMS-F-038, BBMS-F-050, BBMS-F-052.
    """
    requisition = get_object_or_404(Requisition, pk=requisition_pk)

    if requisition.status not in (Requisition.Status.APPROVED, Requisition.Status.PARTIALLY_FULFILLED):
        messages.error(
            request,
            f"Requisition {requisition.requisition_id} is in status '{requisition.status}' "
            f"and cannot receive allocations."
        )
        return redirect('requisitions:detail', pk=requisition.pk)

    current_reserved = requisition.allocations.filter(status=AllocationStatus.RESERVED).count()
    remaining_unreserved = requisition.remaining_quantity - current_reserved

    if remaining_unreserved <= 0:
        messages.info(
            request,
            f"Requisition {requisition.requisition_id} already has all required units reserved or dispatched."
        )
        return redirect('requisitions:detail', pk=requisition.pk)

    if request.method == 'POST':
        form = AllocationForm(request.POST)
        if form.is_valid():
            unit_ids = form.cleaned_data['unit_ids']
            override_reason = form.cleaned_data.get('override_reason', '')
            try:
                allocations = allocate_units_to_requisition(
                    requisition_pk=requisition.pk,
                    unit_ids=unit_ids,
                    actor=request.user,
                    override_reason=override_reason,
                )
                messages.success(
                    request,
                    f"Successfully allocated {len(allocations)} unit(s) to requisition {requisition.requisition_id} "
                    f"(SRS BBMS-F-052)."
                )
                return redirect('requisitions:detail', pk=requisition.pk)
            except ValidationError as exc:
                messages.error(request, str(exc.message if hasattr(exc, 'message') else exc))
            except AllocationConflict as exc:
                messages.error(request, str(exc))
        else:
            messages.error(request, "Please correct the errors below.")
    else:
        form = AllocationForm()

    fefo_suggestions = get_fefo_allocation_suggestions(requisition)
    all_available = get_available_units_for_requisition(requisition)

    return render(request, 'inventory/allocate.html', {
        'requisition': requisition,
        'remaining_unreserved': remaining_unreserved,
        'current_reserved': current_reserved,
        'fefo_suggestions': fefo_suggestions,
        'available_units': all_available,
        'form': form,
    })


@role_required(User.Role.STAFF, User.Role.ADMIN)
def dispatch_requisition_view(request, requisition_pk):
    """
    Staff view for generating a dispatch manifest and dispatching reserved units.
    SRS BBMS-F-053, BBMS-F-054, BBMS-F-055.
    """
    requisition = get_object_or_404(Requisition, pk=requisition_pk)

    if requisition.status not in (Requisition.Status.APPROVED, Requisition.Status.PARTIALLY_FULFILLED):
        messages.error(
            request,
            f"Requisition {requisition.requisition_id} is in status '{requisition.status}' and cannot be dispatched."
        )
        return redirect('requisitions:detail', pk=requisition.pk)

    reserved_allocations = list(
        requisition.allocations.filter(status=AllocationStatus.RESERVED).select_related('blood_unit')
    )

    if not reserved_allocations:
        messages.warning(
            request,
            f"Requisition {requisition.requisition_id} has no reserved units to dispatch. Allocate units first."
        )
        return redirect('inventory:allocate_requisition', requisition_pk=requisition.pk)

    if request.method == 'POST':
        form = DispatchForm(request.POST)
        if form.is_valid():
            unit_ids = form.cleaned_data['unit_ids']
            notes = form.cleaned_data.get('notes', '')
            try:
                manifest, updated_req = dispatch_allocated_units(
                    requisition_pk=requisition.pk,
                    unit_ids=unit_ids,
                    actor=request.user,
                    notes=notes,
                )
                messages.success(
                    request,
                    f"Dispatch successful! Generated Manifest {manifest.manifest_id}. "
                    f"Requisition status: {updated_req.status} (SRS BBMS-F-053, BBMS-F-055)."
                )
                return redirect('inventory:manifest_detail', manifest_id=manifest.manifest_id)
            except ValidationError as exc:
                messages.error(request, str(exc.message if hasattr(exc, 'message') else exc))
            except AllocationConflict as exc:
                messages.error(request, str(exc))
        else:
            messages.error(request, "Please correct the errors in the dispatch form.")
    else:
        all_unit_ids = ','.join(str(a.blood_unit_id) for a in reserved_allocations)
        form = DispatchForm(initial={'unit_ids': all_unit_ids})

    return render(request, 'inventory/dispatch.html', {
        'requisition': requisition,
        'reserved_allocations': reserved_allocations,
        'form': form,
    })


def manifest_detail_view(request, manifest_id):
    """
    Readable and printable dispatch manifest document view.
    SRS BBMS-F-053.
    """
    manifest = get_object_or_404(
        DispatchManifest.objects.select_related('requisition', 'requisition__hospital', 'dispatched_by'),
        manifest_id=manifest_id
    )

    user = request.user
    if not user.is_authenticated:
        return redirect('accounts:login')

    is_staff = user.role in (User.Role.STAFF, User.Role.ADMIN) or user.is_staff or user.is_superuser
    is_owner = user.role == User.Role.HOSPITAL and manifest.requisition.hospital_id == user.pk

    if not (is_staff or is_owner):
        raise PermissionDenied("You do not have permission to view this dispatch manifest.")

    units = list(manifest.units.all().select_related('collected_by', 'donor'))

    return render(request, 'inventory/manifest_detail.html', {
        'manifest': manifest,
        'requisition': manifest.requisition,
        'units': units,
        'is_staff': is_staff,
    })


# ==============================================================================
# REST API Endpoints (SAD Section 4.3)
# ==============================================================================

@never_cache
@role_required(User.Role.STAFF, User.Role.ADMIN)
@require_safe
def api_fefo_suggestions(request, requisition_pk):
    """
    REST API returning FEFO suggested blood units for an approved requisition.
    GET /api/inventory/requisitions/{pk}/suggestions/
    SRS BBMS-F-038.
    """
    requisition = get_object_or_404(Requisition, pk=requisition_pk)
    suggestions = get_fefo_allocation_suggestions(requisition)

    data = {
        'requisition_id': requisition.requisition_id,
        'blood_group': requisition.blood_group,
        'component_type': requisition.component_type,
        'remaining_quantity': requisition.remaining_quantity,
        'suggested_units': [
            {
                'id': u.id,
                'bag_id': u.bag_id,
                'blood_group': u.blood_group,
                'component_type': u.component_type,
                'expiry_date': u.expiry_date.isoformat() if u.expiry_date else None,
                'collection_date': u.collection_date.isoformat(),
                'location': u.location,
            }
            for u in suggestions
        ],
    }
    return JsonResponse(data, status=200)


@never_cache
@role_required(User.Role.STAFF, User.Role.ADMIN)
@require_http_methods(["POST"])
def api_allocate_units(request, requisition_pk):
    """
    REST API for atomically allocating blood units to an approved requisition.
    POST /api/inventory/requisitions/{pk}/allocate/
    SRS BBMS-F-050, BBMS-F-052.
    """
    try:
        body = json.loads(request.body.decode('utf-8'))
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON body.'}, status=400)

    unit_ids = body.get('unit_ids')
    override_reason = body.get('override_reason', '')
    expected_version = body.get('expected_version')

    if not isinstance(unit_ids, list) or not unit_ids:
        return JsonResponse({'error': 'unit_ids must be a non-empty array of integers.'}, status=400)

    try:
        allocations = allocate_units_to_requisition(
            requisition_pk=requisition_pk,
            unit_ids=unit_ids,
            actor=request.user,
            override_reason=override_reason,
            expected_version=expected_version,
        )
        return JsonResponse({
            'status': 'success',
            'allocated_count': len(allocations),
            'allocations': [
                {
                    'allocation_id': a.allocation_id,
                    'bag_id': a.blood_unit.bag_id,
                    'cross_match_outcome': a.cross_match_outcome,
                    'status': a.status,
                }
                for a in allocations
            ]
        }, status=201)
    except AllocationConflict as exc:
        return JsonResponse({'error': str(exc)}, status=409)
    except ValidationError as exc:
        msg = exc.message if hasattr(exc, 'message') else str(exc)
        return JsonResponse({'error': msg}, status=400)


@never_cache
@role_required(User.Role.STAFF, User.Role.ADMIN)
@require_http_methods(["POST"])
def api_dispatch_units(request, requisition_pk):
    """
    REST API for executing dispatch against reserved units and creating manifest.
    POST /api/inventory/requisitions/{pk}/dispatch/
    SRS BBMS-F-053, BBMS-F-054, BBMS-F-055.
    """
    try:
        body = json.loads(request.body.decode('utf-8'))
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON body.'}, status=400)

    unit_ids = body.get('unit_ids')
    notes = body.get('notes', '')
    expected_version = body.get('expected_version')

    if not isinstance(unit_ids, list) or not unit_ids:
        return JsonResponse({'error': 'unit_ids must be a non-empty array of integers.'}, status=400)

    try:
        manifest, updated_req = dispatch_allocated_units(
            requisition_pk=requisition_pk,
            unit_ids=unit_ids,
            actor=request.user,
            notes=notes,
            expected_version=expected_version,
        )
        return JsonResponse({
            'status': 'success',
            'manifest_id': manifest.manifest_id,
            'dispatched_at': manifest.dispatched_at.isoformat(),
            'requisition_status': updated_req.status,
            'dispatched_quantity': updated_req.dispatched_quantity,
            'remaining_quantity': updated_req.remaining_quantity,
            'bag_ids': manifest.bag_ids,
        }, status=200)
    except AllocationConflict as exc:
        return JsonResponse({'error': str(exc)}, status=409)
    except ValidationError as exc:
        msg = exc.message if hasattr(exc, 'message') else str(exc)
        return JsonResponse({'error': msg}, status=400)


@never_cache
@require_safe
def api_manifest_detail(request, manifest_id):
    """
    REST API endpoint returning dispatch manifest details.
    GET /api/inventory/manifests/{manifest_id}/
    SRS BBMS-F-053.
    """
    manifest = get_object_or_404(
        DispatchManifest.objects.select_related('requisition', 'requisition__hospital', 'dispatched_by'),
        manifest_id=manifest_id
    )

    user = request.user
    if not user.is_authenticated:
        return JsonResponse({'error': 'Authentication required.'}, status=401)

    is_staff = user.role in (User.Role.STAFF, User.Role.ADMIN) or user.is_staff or user.is_superuser
    is_owner = user.role == User.Role.HOSPITAL and manifest.requisition.hospital_id == user.pk

    if not (is_staff or is_owner):
        return JsonResponse({'error': 'Access denied.'}, status=403)

    return JsonResponse({
        'manifest_id': manifest.manifest_id,
        'requisition_id': manifest.requisition.requisition_id,
        'hospital': manifest.requisition.hospital.hospital_name or manifest.requisition.hospital.username,
        'dispatched_by': manifest.dispatched_by.username,
        'dispatched_at': manifest.dispatched_at.isoformat(),
        'notes': manifest.notes,
        'units': [
            {
                'bag_id': u.bag_id,
                'blood_group': u.blood_group,
                'component_type': u.component_type,
                'volume_ml': u.volume_ml,
                'expiry_date': u.expiry_date.isoformat() if u.expiry_date else None,
            }
            for u in manifest.units.all()
        ],
    }, status=200)


@role_required(User.Role.STAFF, User.Role.ADMIN)
@require_http_methods(["GET", "POST"])
def separate_blood_unit(request, bag_id):
    """
    Staff interface to separate a safe Whole Blood unit into traceable components
    (RBC, Platelets, Plasma).
    SRS References:
    - Section 4.10 (BBMS-F-031, BBMS-F-032): Component Separation & Traceability
    - Section 4.12 (BBMS-F-037): Component Expiry Calculation
    """
    unit = get_object_or_404(
        BloodUnit.objects.select_related('donor', 'lab_confirmed_by', 'collected_by')
        .prefetch_related('serology_tests', 'child_components'),
        bag_id=bag_id
    )

    # 1. API / JSON Request handling
    if _is_api_request(request) or request.content_type == 'application/json':
        if request.method != 'POST':
            return JsonResponse({'error': 'POST method required for separation.'}, status=405)

        try:
            body = json.loads(request.body.decode('utf-8')) if request.body else {}
        except json.JSONDecodeError:
            return JsonResponse({'error': 'Malformed JSON payload.'}, status=400)

        components_data = body.get('components')
        notes = body.get('notes', '')

        try:
            children = unit.separate_into_components(
                components_data=components_data,
                staff_user=request.user,
                notes=notes
            )
        except ValidationError as exc:
            return JsonResponse({'error': str(exc.message if hasattr(exc, 'message') else exc)}, status=400)
        except Exception as exc:
            return JsonResponse({'error': str(exc)}, status=400)

        child_list = []
        for child in children:
            child_list.append({
                'bag_id': child.bag_id,
                'component_type': child.component_type,
                'volume_ml': child.volume_ml,
                'blood_group': child.blood_group,
                'expiry_date': child.expiry_date.isoformat() if child.expiry_date else None,
                'status': child.status,
                'parent_bag_id': unit.bag_id,
            })

        return JsonResponse({
            'success': True,
            'message': (
                f"Whole blood unit {unit.bag_id} successfully separated into "
                f"{len(children)} component(s)."
            ),
            'parent_bag_id': unit.bag_id,
            'parent_status': unit.status,
            'components': child_list,
        }, status=201)

    # 2. HTML Form GET
    if request.method == 'GET':
        if not unit.can_be_separated:
            reasons = []
            if unit.component_type != ComponentType.WHOLE_BLOOD:
                reasons.append(f"unit is '{unit.component_type}', not Whole Blood")
            if unit.status != BloodUnitStatus.AVAILABLE:
                reasons.append(f"unit status is '{unit.status}' (must be Available)")
            if unit.is_expired:
                reasons.append("unit is expired")
            if not unit.has_passed_serology:
                reasons.append("unit has not passed all 4 mandatory serology tests")
            if unit.is_separated or unit.child_components.exists():
                reasons.append("unit has already been separated")

            err_msg = f"Unit {unit.bag_id} is not eligible for component separation: {', '.join(reasons)}."
            messages.warning(request, err_msg)
            return redirect('inventory:unit_detail', bag_id=unit.bag_id)

        form = ComponentSeparationForm()
        context = {
            'title': f"Component Separation - {unit.bag_id}",
            'unit': unit,
            'form': form,
        }
        return render(request, 'inventory/separate_unit.html', context)

    # 3. HTML Form POST
    form = ComponentSeparationForm(request.POST)
    if form.is_valid():
        try:
            components_data = form.get_components_data()
            notes = form.cleaned_data.get('notes', '')
            children = unit.separate_into_components(
                components_data=components_data,
                staff_user=request.user,
                notes=notes
            )
            child_ids = ', '.join(c.bag_id for c in children)
            messages.success(
                request,
                f"Unit {unit.bag_id} successfully separated into {len(children)} child component(s): {child_ids}. "
                f"The parent unit is now marked 'Separated' and retired from allocatable stock (SRS BBMS-F-031)."
            )
            return redirect('inventory:unit_detail', bag_id=unit.bag_id)
        except ValidationError as exc:
            messages.error(request, str(exc.message if hasattr(exc, 'message') else exc))
        except Exception as exc:
            messages.error(request, f"Separation error: {exc}")

    context = {
        'title': f"Component Separation - {unit.bag_id}",
        'unit': unit,
        'form': form,
    }
    return render(request, 'inventory/separate_unit.html', context)


@role_required(User.Role.STAFF, User.Role.ADMIN)
@require_http_methods(["POST"])
def api_separate_blood_unit(request, bag_id):
    """
    Dedicated REST API endpoint for component separation.
    SAD Section 4.3: POST /api/blood-units/{bagId}/components (Staff role)
    SRS BBMS-F-031, BBMS-F-032, BBMS-SR-003.
    """
    return separate_blood_unit(request, bag_id)


@role_required(User.Role.STAFF, User.Role.ADMIN)
@require_http_methods(["POST"])
def api_expire_units(request):
    """
    REST API endpoint to trigger automatic inventory expiry processing.
    SRS BBMS-F-037, BBMS-F-038, BBMS-F-039.
    """
    dry_run = False
    as_of = None

    if request.body:
        try:
            body = json.loads(request.body.decode('utf-8'))
            dry_run = bool(body.get('dry_run', False))
            as_of_raw = body.get('as_of')
            if as_of_raw:
                parsed = timezone.datetime.fromisoformat(as_of_raw.replace('Z', '+00:00'))
                if timezone.is_naive(parsed):
                    as_of = timezone.make_aware(parsed, timezone.get_current_timezone())
                else:
                    as_of = parsed
        except Exception as exc:
            return JsonResponse({'error': f"Invalid request body: {exc}"}, status=400)
    else:
        dry_run = request.POST.get('dry_run', '').lower() in ('1', 'true')
        as_of_raw = request.POST.get('as_of')
        if as_of_raw:
            try:
                parsed = timezone.datetime.fromisoformat(as_of_raw.replace('Z', '+00:00'))
                as_of = (
                    timezone.make_aware(parsed, timezone.get_current_timezone())
                    if timezone.is_naive(parsed) else parsed
                )
            except Exception as exc:
                return JsonResponse({'error': f"Invalid as_of value: {exc}"}, status=400)

    result = process_expired_units(as_of=as_of, dry_run=dry_run, actor=request.user)

    formatted_units = []
    for item in result['expired_units']:
        formatted_units.append({
            'bag_id': item['bag_id'],
            'previous_status': item['previous_status'],
            'new_status': item['new_status'],
            'blood_group': item['blood_group'],
            'component_type': item['component_type'],
            'expiry_date': item['expiry_date'].isoformat() if item['expiry_date'] else None,
            'reason': item['reason'],
        })

    return JsonResponse({
        'success': True,
        'processed_count': result['processed_count'],
        'expired_units': formatted_units,
        'as_of': result['as_of'].isoformat(),
        'dry_run': result['dry_run'],
    }, status=200)
