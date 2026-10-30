"""
Central Security and Domain Audit Service (SRS BBMS-SR-008, BBMS-F-058, BBMS-F-059).
Provides structured, append-only recording of authentication, lockout, recovery,
donor/user/unit/requisition domain actions, and role/approval modifications.
Features automated secret/medical scrubbing, timestamped logging, and verifiable
cryptographic SHA-256 hash chaining for tamper evidence.
"""
from datetime import datetime
import hashlib
import json
import logging
import time
from django.conf import settings
from django.db import OperationalError, transaction
from django.utils import timezone
from .models import SecurityAuditEvent

logger = logging.getLogger('bbms.security')

GENESIS_PREV_HASH = '0' * 64

# Sensitive credential, session, and clinical keywords to scrub from audit records
# (SRS BBMS-SR-008, BBMS-F-058, Issue #47)
SENSITIVE_KEYWORDS = {
    'password', 'token', 'secret', 'key', 'credential',
    'authorization', 'cookie', 'session', 'csrf', 'hash',
    # Unnecessary medical details to omit
    'medical_history', 'medical_details', 'questionnaire', 'responses',
    'answers', 'conditions', 'medications', 'diagnosis', 'symptoms',
    'screening_responses', 'ineligibility_reason',
}


def sanitize_audit_details(details):
    """
    Recursively scrubs sensitive keys and values from audit detail dictionaries
    to ensure credentials, tokens, or unnecessary medical details are never
    persisted in audit storage or logs (SRS BBMS-SR-008, BBMS-F-058).
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


def canonical_details_json(details):
    """
    Serializes details dictionary into a canonical, deterministic JSON string
    with sorted keys and compact delimiters.
    """
    if not details:
        return '{}'
    return json.dumps(details, sort_keys=True, separators=(',', ':'))


def format_audit_timestamp(timestamp):
    """
    Formats a datetime object or string to a canonical ISO-8601 string representation.
    """
    if isinstance(timestamp, datetime):
        return timestamp.isoformat()
    return str(timestamp)


def calculate_event_hash(
    prev_hash,
    timestamp,
    action,
    severity,
    actor_label,
    ip_address,
    target_type,
    target_id,
    details,
):
    """
    Computes a cryptographic SHA-256 digest sealing an audit event's content and its
    preceding chain linkage (SRS BBMS-SR-008, BBMS-F-058).
    """
    prev_h = str(prev_hash or GENESIS_PREV_HASH).strip()
    ts_str = format_audit_timestamp(timestamp)
    details_str = canonical_details_json(details)

    fields = [
        f"prev_hash={prev_h}",
        f"timestamp={ts_str}",
        f"action={action or ''}",
        f"severity={severity or ''}",
        f"actor_label={actor_label or ''}",
        f"ip_address={ip_address or ''}",
        f"target_type={target_type or ''}",
        f"target_id={target_id or ''}",
        f"details={details_str}",
    ]
    raw_payload = '|'.join(fields)
    return hashlib.sha256(raw_payload.encode('utf-8')).hexdigest()


def with_audit_retry(operation, max_retries=10, delay=0.03):
    """
    Retries database operations encountering transient SQLite table/database locks
    under concurrent append conditions.
    """
    for attempt in range(max_retries):
        try:
            return operation()
        except OperationalError as exc:
            if 'locked' in str(exc).lower() and attempt < max_retries - 1:
                time.sleep(delay * (attempt + 1))
                continue
            raise


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
    timestamp=None,
):
    """
    Records a structured security or domain event to the central append-only audit store
    and the timestamped server security log with cryptographic hash chaining (SRS BBMS-SR-008).
    """
    # 1. Resolve actor
    if actor is None and request and getattr(request, 'user', None) and request.user.is_authenticated:
        actor = request.user

    if not actor_label:
        if actor and getattr(actor, 'username', None):
            actor_label = actor.username
        elif request and getattr(request, 'user', None) and request.user.is_authenticated:
            actor_label = request.user.username
        else:
            actor_label = 'System'

    # 2. Resolve IP address
    if ip_address is None and request:
        ip_address = extract_client_ip(request)

    # 3. Resolve user agent
    user_agent = ''
    if request:
        user_agent = (request.META.get('HTTP_USER_AGENT') or '')[:512]

    # 4. Sanitize details
    safe_details = sanitize_audit_details(details or {})
    event_timestamp = timestamp or timezone.now()

    def _atomic_insert():
        with transaction.atomic():
            last_record = SecurityAuditEvent.objects.select_for_update().order_by('-id').first()
            if last_record and last_record.record_hash:
                prev_hash = last_record.record_hash
            else:
                prev_hash = GENESIS_PREV_HASH

            record_hash = calculate_event_hash(
                prev_hash=prev_hash,
                timestamp=event_timestamp,
                action=action,
                severity=severity,
                actor_label=actor_label,
                ip_address=ip_address,
                target_type=target_type,
                target_id=str(target_id) if target_id else '',
                details=safe_details,
            )

            event = SecurityAuditEvent(
                timestamp=event_timestamp,
                action=action,
                severity=severity,
                actor=actor,
                actor_label=actor_label,
                ip_address=ip_address,
                user_agent=user_agent,
                target_type=target_type,
                target_id=str(target_id) if target_id else '',
                details=safe_details,
                prev_hash=prev_hash,
                record_hash=record_hash,
            )
            event.save(force_insert=True)
            return event

    event = with_audit_retry(_atomic_insert)

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


# Shared alias for domain audit logging (Issue #47)
record_audit_event = record_security_event


def verify_audit_log_integrity():
    """
    Traverses the central audit log sequence and cryptographically verifies:
    1. Each record's `record_hash` matches its content digest.
    2. The hash chain is unbroken: each record's `prev_hash` strictly equals the
       preceding record's `record_hash` (and the genesis record begins with GENESIS_PREV_HASH).
    Returns (is_valid: bool, errors: list[str], verified_count: int).
    """
    records = list(SecurityAuditEvent.objects.order_by('id'))
    errors = []

    if not records:
        return True, [], 0

    previous_hash = GENESIS_PREV_HASH

    for idx, record in enumerate(records):
        # 1. Verify prev_hash linkage
        if record.prev_hash != previous_hash:
            errors.append(
                f"Record ID {record.pk} has broken prev_hash: "
                f"expected '{previous_hash}', found '{record.prev_hash}'."
            )

        # 2. Verify record_hash calculation
        expected_hash = calculate_event_hash(
            prev_hash=record.prev_hash,
            timestamp=record.timestamp,
            action=record.action,
            severity=record.severity,
            actor_label=record.actor_label,
            ip_address=record.ip_address,
            target_type=record.target_type,
            target_id=record.target_id,
            details=record.details,
        )

        if record.record_hash != expected_hash:
            errors.append(
                f"Record ID {record.pk} content has been tampered with: "
                f"expected record_hash '{expected_hash}', found '{record.record_hash}'."
            )

        previous_hash = record.record_hash

    is_valid = len(errors) == 0
    return is_valid, errors, len(records)
