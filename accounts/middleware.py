"""
Middleware for brute-force login rate limiting (SRS BBMS-SR-007).
Enforces at most 10 login requests per minute per source IP across HTML, JSON,
and Django admin login endpoints.
"""
from django.http import HttpResponse, JsonResponse
from django.urls import resolve, Resolver404
from core.audit import extract_client_ip, record_security_event
from .security import check_ip_rate_limit, record_ip_login_request

PROTECTED_VIEW_NAMES = {'accounts:login', 'admin:login'}
PROTECTED_PATHS = {'/accounts/login/', '/admin/login/'}


class LoginProtectionMiddleware:
    """
    Middleware applying IP rate limiting to login endpoints (SRS BBMS-SR-007).
    Limits source IPs to 10 login requests per minute using sliding-window tracking.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def _is_login_post(self, request):
        if request.method != 'POST':
            return False

        path = request.path_info
        if path in PROTECTED_PATHS or path.rstrip('/') in {'/accounts/login', '/admin/login'}:
            return True

        try:
            resolved = resolve(path)
            if resolved and resolved.view_name in PROTECTED_VIEW_NAMES:
                return True
        except Resolver404:
            pass

        return False

    def __call__(self, request):
        if self._is_login_post(request):
            is_limited, count = check_ip_rate_limit(request)
            if is_limited:
                client_ip = extract_client_ip(request)
                record_security_event(
                    action='ip_rate_limited',
                    request=request,
                    ip_address=client_ip,
                    target_type='ip',
                    target_id=client_ip or '',
                    details={
                        'path': request.path_info,
                        'recent_requests_count': count,
                        'rate_limit': 10,
                    },
                    severity='WARNING',
                )
                headers = {'Retry-After': '60'}
                msg = 'Too many login requests from this IP address. Please try again later.'
                is_json = (
                    request.headers.get('x-requested-with') == 'XMLHttpRequest' or
                    'application/json' in request.META.get('CONTENT_TYPE', '')
                )
                if is_json:
                    return JsonResponse({'error': msg}, status=429, headers=headers)
                return HttpResponse(msg, status=429, content_type='text/plain', headers=headers)

            record_ip_login_request(request)

        return self.get_response(request)
