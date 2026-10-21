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
from django.core.exceptions import ValidationError
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from accounts.models import User
from accounts.rbac import _is_api_request, role_required
from core.constants import BloodGroup, VALID_BLOOD_GROUPS
from .forms import BloodCollectionForm, BloodGroupCorrectionForm, SerologyPanelForm
from .models import (
    BloodUnit,
    BloodUnitStatus,
    ComponentType,
    SerologyResult,
    SerologyTestType,
)


@role_required(User.Role.STAFF, User.Role.ADMIN)
def inventory_dashboard(request):
    """
    Inventory management dashboard for staff and administrators.
    Displays units grouped by the eight ABO/Rh blood groups, component types,
    and FEFO expiry metrics (SRS BBMS-F-022, BBMS-F-033, BBMS-F-034).
    """
    now = timezone.now()
    soon_threshold = now + timedelta(days=7)

    available_units_qs = BloodUnit.objects.filter(status=BloodUnitStatus.AVAILABLE)
    total_units_available = available_units_qs.count()
    quarantined_units = BloodUnit.objects.filter(status=BloodUnitStatus.QUARANTINED).count()
    expiring_soon_count = available_units_qs.filter(
        expiry_date__lte=soon_threshold,
        expiry_date__gt=now
    ).count()

    # Aggregate stock counts for all 8 standard blood groups and components
    stock_matrix = []
    for bg_val, bg_label in BloodGroup.choices:
        wb_count = available_units_qs.filter(blood_group=bg_val, component_type=ComponentType.WHOLE_BLOOD).count()
        rbc_count = available_units_qs.filter(blood_group=bg_val, component_type=ComponentType.RBC).count()
        plt_count = available_units_qs.filter(blood_group=bg_val, component_type=ComponentType.PLATELETS).count()
        ffp_count = available_units_qs.filter(blood_group=bg_val, component_type=ComponentType.PLASMA).count()
        total_bg = wb_count + rbc_count + plt_count + ffp_count

        stock_matrix.append({
            'blood_group': bg_val,
            'whole_blood': wb_count,
            'rbc': rbc_count,
            'platelets': plt_count,
            'plasma': ffp_count,
            'total': total_bg,
        })

    # Recent units across all statuses
    recent_units = BloodUnit.objects.select_related('donor', 'lab_confirmed_by').order_by('-collection_date')[:15]

    context = {
        'title': 'Blood Inventory Dashboard',
        'blood_groups': VALID_BLOOD_GROUPS,
        'stock_matrix': stock_matrix,
        'total_units_available': total_units_available,
        'quarantined_units': quarantined_units,
        'expiring_soon_count': expiring_soon_count,
        'recent_units': recent_units,
    }
    return render(request, 'inventory/dashboard.html', context)


@role_required(User.Role.STAFF, User.Role.ADMIN)
def quarantine_list(request):
    """
    List units pending serology testing or under quarantine.
    Displays elapsed quarantine time, Bag ID, and lab-confirmed vs self-reported blood group.
    SRS: 4.8, 4.9 (BBMS-F-026 to BBMS-F-030).
    """
    quarantined_qs = BloodUnit.objects.filter(
        status=BloodUnitStatus.QUARANTINED
    ).select_related('donor', 'lab_confirmed_by').order_by('-collection_date')

    context = {
        'title': 'Quarantine & Serology Testing',
        'quarantined_units': quarantined_qs,
    }
    return render(request, 'inventory/quarantine.html', context)


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
        BloodUnit.objects.prefetch_related('serology_tests'),
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


