"""
Central Security Audit Service (SRS BBMS-SR-008, BBMS-F-058).
Provides structured recording of authentication, lockout, password recovery, and security events
with automated secret scrubbing and timestamped logging.
"""
import logging
from django.conf import settings
from django.utils import timezone
from .models import SecurityAuditEvent

logger = logging.getLogger('bbms.security')

SENSITIVE_KEYWORDS = {
    'password', 'token', 'secret', 'key', 'credential',
    'authorization', 'cookie', 'session', 'csrf', 'hash',
}


def sanitize_audit_details(details):
    """
    Recursively scrubs sensitive keys and values from audit detail dictionaries
    to ensure credentials or tokens are never persisted in audit storage or logs.
    """
    if not isinstance(details, dict):
        return {}

    cleaned = {}
    for key, value in details.items():
        key_str = str(key).lower()
        if any(keyword in key_str for keyword in SENSITIVE_KEYWORDS):
            continue
        if isinstance(value, dict):
            cleaned[key] = sanitize_audit_details(value)
        elif isinstance(value, (list, tuple, set)):
            cleaned[key] = [
                sanitize_audit_details(item) if isinstance(item, dict) else item
                for item in value
            ]
        elif isinstance(value, (str, int, float, bool)) or value is None:
            cleaned[key] = value
        else:
            cleaned[key] = str(value)
    return cleaned


def extract_client_ip(request):
    """
    Authoritatively extracts peer or trusted forwarded IP address.
    Trusts forwarded headers only when the direct connection originates from an
    explicitly configured trusted reverse proxy (BBMS_TRUSTED_PROXIES).
    """
    if not request:
        return None

    remote_addr = (request.META.get('REMOTE_ADDR') or '').strip()
    trusted_proxies = getattr(settings, 'BBMS_TRUSTED_PROXIES', [])
    if isinstance(trusted_proxies, str):
        trusted_proxies = [p.strip() for p in trusted_proxies.split(',') if p.strip()]

    if remote_addr in trusted_proxies:
        xff = request.META.get('HTTP_X_FORWARDED_FOR', '')
        if xff:
            ips = [ip.strip() for ip in xff.split(',') if ip.strip()]
            for ip in reversed(ips):
                if ip not in trusted_proxies:
                    return ip
            if ips:
                return ips[0]

    return remote_addr or None


def record_security_event(
    action,
    request=None,
    actor=None,
    actor_label='',
    ip_address=None,
    target_type='',
    target_id='',
    details=None,
    severity=SecurityAuditEvent.Severity.INFO,
):
    """
    Records a structured security event to the central append-only audit store
    and the timestamped server security log without leaking credentials.
    """
    # Resolve actor
    if actor is None and request and getattr(request, 'user', None) and request.user.is_authenticated:
        actor = request.user

    if not actor_label:
        if actor and getattr(actor, 'username', None):
            actor_label = actor.username
        elif request and getattr(request, 'user', None) and request.user.is_authenticated:
            actor_label = request.user.username
        else:
            actor_label = 'anonymous'

    # Resolve IP address
    if ip_address is None and request:
        ip_address = extract_client_ip(request)

    # Resolve user agent
    user_agent = ''
    if request:
        user_agent = (request.META.get('HTTP_USER_AGENT') or '')[:512]

    # Sanitize details
    safe_details = sanitize_audit_details(details or {})

    # Create audit record
    event = SecurityAuditEvent.objects.create(
        timestamp=timezone.now(),
        action=action,
        severity=severity,
        actor=actor,
        actor_label=actor_label,
        ip_address=ip_address,
        user_agent=user_agent,
        target_type=target_type,
        target_id=str(target_id) if target_id else '',
        details=safe_details,
    )

    # Emit timestamped log
    log_msg = (
        f"SECURITY_EVENT: action={action} severity={severity} "
        f"actor={actor_label} ip={ip_address or 'none'} details={safe_details}"
    )
    if severity == SecurityAuditEvent.Severity.CRITICAL:
        logger.critical(log_msg)
    elif severity == SecurityAuditEvent.Severity.ERROR:
        logger.error(log_msg)
    elif severity == SecurityAuditEvent.Severity.WARNING:
        logger.warning(log_msg)
    else:
        logger.info(log_msg)

    return event
