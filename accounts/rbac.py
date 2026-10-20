"""
Role-Based Access Control (RBAC) Module for Blood Bank Management System (BBMS).
SRS References: Section 2.3, Section 4.20 (BBMS-F-061), Section 5.1.2 (BBMS-SR-003).
SAD References: Section 3.9 (Security Architecture), Section 4.3 (Role check Stage 3).
"""

from functools import wraps
from django.conf import settings
from django.contrib.auth.mixins import AccessMixin
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied
from django.http import JsonResponse


# ==============================================================================
# BBMS Granular Domain Permissions
# ==============================================================================

# Donor permissions (SRS 4.1 - 4.4)
PERM_DONOR_PROFILE = 'donor:profile'
PERM_DONOR_HISTORY = 'donor:history'
PERM_DONOR_ELIGIBILITY = 'donor:eligibility'
PERM_BOOK_APPOINTMENT = 'appointments:book'
PERM_CANCEL_APPOINTMENT = 'appointments:cancel'

# Hospital permissions (SRS 4.13 - 4.15, 4.18)
PERM_SUBMIT_REQUISITION = 'requisitions:submit'
PERM_VIEW_REQUISITION = 'requisitions:view'
PERM_CONFIRM_DELIVERY = 'deliveries:confirm'

# Blood Bank Staff permissions (SRS 4.5 - 4.12, 4.16 - 4.17)
PERM_RECORD_COLLECTION = 'collections:record'
PERM_RECORD_SEROLOGY = 'serology:record'
PERM_MANAGE_QUARANTINE = 'quarantine:manage'
PERM_SEPARATE_COMPONENTS = 'components:separate'
PERM_MANAGE_INVENTORY = 'inventory:manage'
PERM_CROSS_MATCH = 'matching:cross_match'
PERM_ALLOCATE_UNITS = 'allocation:allocate'
PERM_DISPATCH_UNITS = 'dispatch:dispatch'
PERM_APPROVE_REQUISITIONS = 'requisitions:approve'

# Administrator permissions (SRS 4.19 - 4.21)
PERM_MANAGE_USERS = 'admin:manage_users'
PERM_APPROVE_HOSPITALS = 'admin:approve_hospitals'
PERM_VIEW_AUDIT_LOGS = 'admin:audit_logs'
PERM_GENERATE_REPORTS = 'admin:reports'


# Role to Permission Matrix (SRS BBMS-F-061)
ROLE_PERMISSIONS = {
    'DONOR': {
        PERM_DONOR_PROFILE,
        PERM_DONOR_HISTORY,
        PERM_DONOR_ELIGIBILITY,
        PERM_BOOK_APPOINTMENT,
        PERM_CANCEL_APPOINTMENT,
    },
    'HOSPITAL': {
        PERM_SUBMIT_REQUISITION,
        PERM_VIEW_REQUISITION,
        PERM_CONFIRM_DELIVERY,
    },
    'STAFF': {
        PERM_RECORD_COLLECTION,
        PERM_RECORD_SEROLOGY,
        PERM_MANAGE_QUARANTINE,
        PERM_SEPARATE_COMPONENTS,
        PERM_MANAGE_INVENTORY,
        PERM_CROSS_MATCH,
        PERM_ALLOCATE_UNITS,
        PERM_DISPATCH_UNITS,
        PERM_APPROVE_REQUISITIONS,
        PERM_VIEW_REQUISITION,
    },
    'ADMIN': {
        PERM_RECORD_COLLECTION,
        PERM_RECORD_SEROLOGY,
        PERM_MANAGE_QUARANTINE,
        PERM_SEPARATE_COMPONENTS,
        PERM_MANAGE_INVENTORY,
        PERM_CROSS_MATCH,
        PERM_ALLOCATE_UNITS,
        PERM_DISPATCH_UNITS,
        PERM_APPROVE_REQUISITIONS,
        PERM_VIEW_REQUISITION,
        PERM_MANAGE_USERS,
        PERM_APPROVE_HOSPITALS,
        PERM_VIEW_AUDIT_LOGS,
        PERM_GENERATE_REPORTS,
    },
}


def _is_api_request(request):
    """
    Check if the incoming HTTP request is targeting an API endpoint or expects JSON.
    """
    accept = request.headers.get('accept', '')
    x_requested = request.headers.get('x-requested-with', '')
    return (
        request.path.startswith('/api/') or
        'application/json' in accept or
        x_requested == 'XMLHttpRequest' or
        request.content_type == 'application/json'
    )


def role_required(*allowed_roles):
    """
    View decorator that enforces Role-Based Access Control (RBAC) on the server side.
    SRS BBMS-SR-003: "The system shall enforce role-based access control (RBAC)
    on the server side for every API endpoint, independent of client-side UI
    restrictions, and shall deny unauthorized requests with an HTTP 403 response."
    """
    # Normalize roles to string identifiers
    normalized_roles = {
        role.value if hasattr(role, 'value') else str(role)
        for role in allowed_roles
    }

    def decorator(view_func):
        @wraps(view_func)
        def _wrapped_view(request, *args, **kwargs):
            # 1. Unauthenticated users redirected to login
            if not request.user.is_authenticated:
                if _is_api_request(request):
                    return JsonResponse(
                        {'error': 'Authentication required (SRS BBMS-SR-001).'},
                        status=401
                    )
                return redirect_to_login(request.get_full_path(), settings.LOGIN_URL)

            # 2. Deactivated accounts blocked (SRS BBMS-F-063)
            if not request.user.is_active:
                if _is_api_request(request):
                    return JsonResponse({'error': 'Account is deactivated (SRS BBMS-F-063).'}, status=403)
                raise PermissionDenied('Account is deactivated (SRS BBMS-F-063).')

            # 3. Unapproved hospital accounts blocked from privileged actions (SRS BBMS-F-042)
            if request.user.role == 'HOSPITAL' and not request.user.is_approved:
                if _is_api_request(request):
                    return JsonResponse(
                        {'error': 'Hospital account is pending administrator approval (SRS BBMS-F-042).'},
                        status=403
                    )
                raise PermissionDenied('Hospital account is pending administrator approval (SRS BBMS-F-042).')

            # 4. Check role membership (Superusers satisfy ADMIN and STAFF)
            user_role = getattr(request.user, 'role', None)
            is_authorized = (
                user_role in normalized_roles or
                request.user.is_superuser or
                ('ADMIN' in normalized_roles and request.user.is_superuser) or
                ('STAFF' in normalized_roles and (request.user.is_staff or request.user.is_superuser))
            )

            if not is_authorized:
                if _is_api_request(request):
                    return JsonResponse(
                        {'error': 'Forbidden: You lack the required role to access this resource (SRS BBMS-SR-003).'},
                        status=403
                    )
                raise PermissionDenied('You lack the required role to access this resource (SRS BBMS-SR-003).')

            return view_func(request, *args, **kwargs)
        return _wrapped_view
    return decorator


def permission_required_custom(perm_code):
    """
    View decorator checking a granular BBMS domain permission.
    SRS BBMS-F-061, BBMS-SR-003.
    """
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped_view(request, *args, **kwargs):
            if not request.user.is_authenticated:
                if _is_api_request(request):
                    return JsonResponse({'error': 'Authentication required.'}, status=401)
                return redirect_to_login(request.get_full_path(), settings.LOGIN_URL)

            if not request.user.is_active:
                raise PermissionDenied('Account is deactivated.')

            if not request.user.has_perm_code(perm_code):
                if _is_api_request(request):
                    return JsonResponse(
                        {'error': f'Forbidden: Missing permission {perm_code} (SRS BBMS-SR-003).'},
                        status=403
                    )
                raise PermissionDenied(f'Forbidden: Missing permission {perm_code}.')

            return view_func(request, *args, **kwargs)
        return _wrapped_view
    return decorator


class RoleRequiredMixin(AccessMixin):
    """
    Class-based view mixin to enforce role permissions.
    """
    allowed_roles = ()

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()

        if not request.user.is_active:
            raise PermissionDenied('Account is deactivated (SRS BBMS-F-063).')

        if request.user.role == 'HOSPITAL' and not request.user.is_approved:
            raise PermissionDenied('Hospital account is pending administrator approval (SRS BBMS-F-042).')

        normalized_roles = {
            role.value if hasattr(role, 'value') else str(role)
            for role in self.allowed_roles
        }

        user_role = getattr(request.user, 'role', None)
        is_authorized = (
            user_role in normalized_roles or
            request.user.is_superuser or
            ('ADMIN' in normalized_roles and request.user.is_superuser) or
            ('STAFF' in normalized_roles and (request.user.is_staff or request.user.is_superuser))
        )

        if not is_authorized:
            raise PermissionDenied('You lack the required role to access this resource (SRS BBMS-SR-003).')

        return super().dispatch(request, *args, **kwargs)
