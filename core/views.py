"""
Core views for Blood Bank Management System (BBMS).
SRS: Section 2.1, 3.1, 4.22 (BBMS-F-067, BBMS-F-068), Section 4.19 (BBMS-F-058, BBMS-F-059).
"""
from datetime import datetime
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import HttpResponseNotAllowed, JsonResponse
from django.shortcuts import render
from accounts.rbac import _is_api_request, role_required
from core.audit import verify_audit_log_integrity
from core.constants import VALID_BLOOD_GROUPS
from core.models import SecurityAuditEvent
from inventory.models import BloodUnit


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
        page_size = max(5, min(page_size, 100))
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
