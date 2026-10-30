"""
Core views for Blood Bank Management System (BBMS).
SRS: Section 2.1, 3.1, 4.22 (BBMS-F-067, BBMS-F-068), Section 4.19 (BBMS-F-058, BBMS-F-059).
"""
from datetime import datetime
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import HttpResponse, HttpResponseNotAllowed, JsonResponse
from django.shortcuts import render
from django.utils import timezone
from accounts.models import User
from accounts.rbac import _is_api_request, role_required
from core.audit import verify_audit_log_integrity
from core.constants import VALID_BLOOD_GROUPS
from core.models import SecurityAuditEvent
from core.reports import (
    generate_donations_csv,
    generate_inventory_csv,
    generate_requisitions_csv,
    get_donation_activity_report_data,
    get_inventory_report_data,
    get_requisition_report_data,
    parse_and_validate_date_range,
)
from inventory.models import BloodUnit
from inventory.services import get_active_locations


def home(request):
    """
    Landing / Home page for BBMS.
    Provides role-oriented call-to-actions and overview.
    SRS: 2.1, 3.1.
    """
    context = {
        'title': 'Blood Bank Management System',
        'stats': {
            'blood_groups_count': len(VALID_BLOOD_GROUPS),
            'standard_components': ['Whole Blood', 'Red Blood Cells', 'Platelets', 'Fresh Frozen Plasma'],
        }
    }
    return render(request, 'core/home.html', context)


def public_availability(request):
    """
    Public-facing blood availability lookup (SRS BBMS-F-067, BBMS-F-068).
    Accessible without authentication; excludes donor/hospital PII.
    Calculates live counts from available blood units across the eight ABO/Rh blood groups.
    """
    available_units = BloodUnit.objects.available()

    inventory_summary = []
    for bg in VALID_BLOOD_GROUPS:
        count = available_units.filter(blood_group=bg).count()
        status_label = 'Adequate' if count >= 10 else 'Low' if count > 0 else 'Critical'
        inventory_summary.append({'blood_group': bg, 'units': count, 'status': status_label})

    context = {
        'title': 'Public Blood Availability',
        'inventory_summary': inventory_summary,
    }
    return render(request, 'core/public_availability.html', context)


def about(request):
    """
    About BBMS, project info, team details, and standard references.
    """
    context = {
        'title': 'About BBMS',
    }
    return render(request, 'core/about.html', context)


@role_required('ADMIN')
def audit_log_view(request):
    """
    Central admin-only paginated read-only viewer for security and domain audit trail
    (SRS BBMS-F-058, BBMS-F-059, BBMS-SR-008, TC-AUD-01).
    Supports filtering by actor, action, severity, target type, and date range.
    Offers content negotiation returning JSON for API consumers and HTML for browser inspection.
    Enforces strict read-only semantics: non-GET requests are rejected with HTTP 405.
    """
    if request.method != 'GET':
        if _is_api_request(request):
            return JsonResponse({'error': 'Method not allowed. Audit log viewer is read-only.'}, status=405)
        return HttpResponseNotAllowed(['GET'])

    queryset = SecurityAuditEvent.objects.select_related('actor').all()

    # Filters
    actor = request.GET.get('actor', '').strip()
    action = request.GET.get('action', '').strip()
    severity = request.GET.get('severity', '').strip()
    target_type = request.GET.get('target_type', '').strip()
    date_from = request.GET.get('start_date') or request.GET.get('date_from', '').strip()
    date_to = request.GET.get('end_date') or request.GET.get('date_to', '').strip()
    search = request.GET.get('q', '').strip()

    if actor:
        queryset = queryset.filter(
            Q(actor_label__icontains=actor) | Q(actor__username__icontains=actor)
        )

    if action:
        queryset = queryset.filter(action=action)

    if severity:
        queryset = queryset.filter(severity=severity)

    if target_type:
        queryset = queryset.filter(target_type=target_type)

    if date_from:
        try:
            parsed_from = datetime.strptime(date_from, '%Y-%m-%d').date()
            queryset = queryset.filter(timestamp__date__gte=parsed_from)
        except ValueError:
            pass

    if date_to:
        try:
            parsed_to = datetime.strptime(date_to, '%Y-%m-%d').date()
            queryset = queryset.filter(timestamp__date__lte=parsed_to)
        except ValueError:
            pass

    if search:
        queryset = queryset.filter(
            Q(actor_label__icontains=search) |
            Q(action__icontains=search) |
            Q(target_id__icontains=search) |
            Q(ip_address__icontains=search)
        )

    # Cryptographic integrity check summary
    is_valid, errors, total_verified = verify_audit_log_integrity()

    # Pagination
    try:
        page_size = int(request.GET.get('page_size', 25))
        page_size = max(1, min(page_size, 100))
    except (ValueError, TypeError):
        page_size = 25

    paginator = Paginator(queryset, page_size)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)

    # JSON API response
    if _is_api_request(request):
        results = [
            {
                'id': ev.pk,
                'timestamp': ev.timestamp.isoformat(),
                'action': ev.action,
                'severity': ev.severity,
                'actor': ev.actor_label or (ev.actor.username if ev.actor else 'System'),
                'actor_id': ev.actor_id,
                'ip_address': ev.ip_address,
                'user_agent': ev.user_agent,
                'target_type': ev.target_type,
                'target_id': ev.target_id,
                'details': ev.details,
                'prev_hash': ev.prev_hash,
                'record_hash': ev.record_hash,
            }
            for ev in page_obj
        ]
        return JsonResponse({
            'count': paginator.count,
            'num_pages': paginator.num_pages,
            'current_page': page_obj.number,
            'has_next': page_obj.has_next(),
            'has_previous': page_obj.has_previous(),
            'integrity_valid': is_valid,
            'total_verified': total_verified,
            'results': results,
        })

    # Prepare active query string for pagination links
    query_params = request.GET.copy()
    if 'page' in query_params:
        del query_params['page']
    filter_querystring = query_params.urlencode()

    # Distinct actions for filter dropdown
    common_actions = [
        'donor_registered',
        'hospital_registered',
        'user_created',
        'role_changed',
        'hospital_approved',
        'hospital_approval_revoked',
        'user_deactivated',
        'user_reactivated',
        'user_deleted',
        'unit_created',
        'unit_status_changed',
        'unit_deleted',
        'requisition_created',
        'requisition_status_changed',
        'requisition_deleted',
        'login_success',
        'login_failed',
        'account_locked',
        'login_attempt_account_locked',
        'lockout_cleared',
        'password_reset_request',
        'password_reset_success',
        'ip_rate_limited',
    ]

    context = {
        'title': 'Audit Log Viewer',
        'page_obj': page_obj,
        'paginator': paginator,
        'integrity_status': {
            'is_valid': is_valid,
            'verified_count': total_verified,
            'errors': errors,
        },
        'filter_querystring': filter_querystring,
        'active_filters': {
            'actor': actor,
            'action': action,
            'severity': severity,
            'target_type': target_type,
            'date_from': date_from,
            'date_to': date_to,
            'search': search,
        },
        'common_actions': common_actions,
        'severity_choices': SecurityAuditEvent.Severity.choices,
    }
    return render(request, 'core/audit_log.html', context)


# ==============================================================================
# Administrative Reports & CSV Analytics (BBMS-F-064 to BBMS-F-066, TC-RPT-01, TC-SEC-03)
# ==============================================================================

@role_required(User.Role.ADMIN)
def reports_dashboard(request):
    """
    Administrative Reports & Analytics Dashboard.
    Provides visual summaries and CSV downloads for:
    - 1. Available Stock Matrix (BBMS-F-064)
    - 2. Donation Activity by Date Range (BBMS-F-065)
    - 3. Requisition & Fulfilment Rates (BBMS-F-066)

    SRS References: BBMS-F-064, BBMS-F-065, BBMS-F-066, BBMS-SR-003, BBMS-SR-005.
    """
    start_date_str = request.GET.get('start_date', '')
    end_date_str = request.GET.get('end_date', '')
    selected_location = request.GET.get('location', '')
    active_tab = request.GET.get('tab', 'overview')

    start_date, end_date, error_message = parse_and_validate_date_range(start_date_str, end_date_str)

    active_locations = get_active_locations()

    inventory_data = get_inventory_report_data(location=selected_location if selected_location != 'ALL' else None)

    if error_message:
        donations_data = None
        requisitions_data = None
    else:
        donations_data = get_donation_activity_report_data(start_date, end_date)
        requisitions_data = get_requisition_report_data(start_date, end_date)

    context = {
        'title': 'Reports & CSV Analytics',
        'start_date': start_date.strftime('%Y-%m-%d') if start_date else '',
        'end_date': end_date.strftime('%Y-%m-%d') if end_date else '',
        'selected_location': selected_location,
        'active_locations': active_locations,
        'active_tab': active_tab,
        'error_message': error_message,
        'inventory_data': inventory_data,
        'donations_data': donations_data,
        'requisitions_data': requisitions_data,
    }
    return render(request, 'core/reports.html', context)


@role_required(User.Role.ADMIN)
def export_inventory_csv(request):
    """
    Downloads inventory stock levels as a formula-safe CSV file.
    SRS BBMS-F-064, BBMS-SR-003, BBMS-SR-005.
    """
    location = request.GET.get('location')
    csv_text = generate_inventory_csv(location=location if location != 'ALL' else None)

    today_str = timezone.localdate().strftime('%Y%m%d')
    filename = f"bbms_inventory_stock_{today_str}.csv"

    response = HttpResponse(csv_text, content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


@role_required(User.Role.ADMIN)
def export_donations_csv(request):
    """
    Downloads donation activity report as a formula-safe CSV file.
    SRS BBMS-F-065, BBMS-SR-003, BBMS-SR-005.
    """
    start_date_str = request.GET.get('start_date', '')
    end_date_str = request.GET.get('end_date', '')

    start_date, end_date, error_message = parse_and_validate_date_range(start_date_str, end_date_str)
    if error_message:
        return HttpResponse(f"Invalid date range: {error_message}", status=400, content_type='text/plain')

    csv_text = generate_donations_csv(start_date, end_date)
    filename = f"bbms_donations_{start_date.strftime('%Y%m%d')}_{end_date.strftime('%Y%m%d')}.csv"

    response = HttpResponse(csv_text, content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


@role_required(User.Role.ADMIN)
def export_requisitions_csv(request):
    """
    Downloads requisition fulfilment report as a formula-safe CSV file.
    SRS BBMS-F-066, BBMS-SR-003, BBMS-SR-005.
    """
    start_date_str = request.GET.get('start_date', '')
    end_date_str = request.GET.get('end_date', '')

    start_date, end_date, error_message = parse_and_validate_date_range(start_date_str, end_date_str)
    if error_message:
        return HttpResponse(f"Invalid date range: {error_message}", status=400, content_type='text/plain')

    csv_text = generate_requisitions_csv(start_date, end_date)
    filename = f"bbms_requisitions_{start_date.strftime('%Y%m%d')}_{end_date.strftime('%Y%m%d')}.csv"

    response = HttpResponse(csv_text, content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


@role_required(User.Role.ADMIN)
def api_reports(request):
    """
    REST API endpoint for reports data (JSON format).
    Supports ?type=inventory|donations|requisitions|all&start_date=YYYY-MM-DD&end_date=YYYY-MM-DD
    """
    report_type = request.GET.get('type', 'all')
    start_date_str = request.GET.get('start_date', '')
    end_date_str = request.GET.get('end_date', '')
    location = request.GET.get('location', '')

    start_date, end_date, error_message = parse_and_validate_date_range(start_date_str, end_date_str)
    if error_message:
        return JsonResponse({'error': error_message}, status=400)

    payload = {}
    if report_type in ('all', 'inventory'):
        payload['inventory'] = get_inventory_report_data(location=location if location != 'ALL' else None)

    if report_type in ('all', 'donations'):
        donations = get_donation_activity_report_data(start_date, end_date)
        # JSON-serializable copy
        payload['donations'] = {
            'start_date': str(donations['start_date']),
            'end_date': str(donations['end_date']),
            'total_donations': donations['total_donations'],
            'collected_units': donations['collected_units'],
            'derived_components_count': donations['derived_components_count'],
            'discarded_units': donations['discarded_units'],
            'unique_donors_count': donations['unique_donors_count'],
            'donations_by_group': donations['donations_by_group'],
            'discarded_by_group': donations['discarded_by_group'],
        }

    if report_type in ('all', 'requisitions'):
        reqs = get_requisition_report_data(start_date, end_date)
        payload['requisitions'] = {
            'start_date': str(reqs['start_date']),
            'end_date': str(reqs['end_date']),
            'total_received': reqs['total_received'],
            'total_fulfilled': reqs['total_fulfilled'],
            'total_partially_fulfilled': reqs['total_partially_fulfilled'],
            'total_rejected': reqs['total_rejected'],
            'total_pending': reqs['total_pending'],
            'total_approved': reqs['total_approved'],
            'total_units_requested': reqs['total_units_requested'],
            'total_units_dispatched': reqs['total_units_dispatched'],
            'manifests_count': reqs['manifests_count'],
            'fulfilment_rate': reqs['fulfilment_rate'],
            'req_by_group': reqs['req_by_group'],
        }

    return JsonResponse(payload)
