"""
Account lockout, credential normalization, and IP rate limiting services (SRS BBMS-SR-007).
Implements the exact SR-007 controls:
- 15-minute account lockout after 5 consecutive failed login attempts.
- At most 10 login requests per minute per source IP (sliding window).
- Atomic shared state suitable for multi-process deployments without per-process dictionaries.
- Strict trusted proxy boundary for source IP extraction.
"""
import time
from datetime import timedelta
from django.db import OperationalError, transaction
from django.db.models import Q
from django.utils import timezone
from core.audit import extract_client_ip, record_security_event
from .models import LoginRateLimitRecord, LoginSecurityState, User

LOCKOUT_THRESHOLD = 5
LOCKOUT_DURATION_SECONDS = 15 * 60  # 15 minutes
IP_RATE_LIMIT_MAX_REQUESTS = 10
IP_RATE_LIMIT_WINDOW_SECONDS = 60  # 1 minute sliding window


def with_db_retry(operation, max_retries=5, delay=0.02):
    """
    Retries database operations encountering transient table/database locks (e.g. SQLite concurrency).
    """
    for attempt in range(max_retries):
        try:
            return operation()
        except OperationalError as exc:
            if 'locked' in str(exc).lower() and attempt < max_retries - 1:
                time.sleep(delay * (attempt + 1))
                continue
            raise


def normalize_identifier(identifier):
    """
    Normalizes a login identifier by stripping whitespace and lowercasing.
    """
    if not identifier:
        return ''
    return str(identifier).strip().lower()


def resolve_account_key_and_user(identifier):
    """
    Normalizes username and email aliases to a canonical account key.
    If the identifier matches an existing account (by username or email),
    the key is 'user:<pk>', guaranteeing that attempts against either alias
    accumulate towards the same lockout counter.
    For unknown identifiers, returns 'unknown:<normalized_identifier>'.
    """
    clean_id = normalize_identifier(identifier)
    if not clean_id:
        return 'anonymous', None

    matching_users = list(
        User.objects.filter(
            Q(username__iexact=clean_id) | Q(email__iexact=clean_id)
        )[:2]
    )

    if len(matching_users) == 1:
        user = matching_users[0]
        return f"user:{user.pk}", user
    elif len(matching_users) > 1:
        return f"ambiguous:{clean_id}", None
    else:
        return f"unknown:{clean_id}", None


def check_account_lockout(identifier, at_time=None):
    """
    Checks if an account is currently locked out under active SR-007 controls.
    Returns (is_locked: bool, state: LoginSecurityState or None).
    """
    key, _ = resolve_account_key_and_user(identifier)
    state = LoginSecurityState.objects.filter(identifier=key).first()
    if not state:
        return False, None

    now = at_time or timezone.now()
    if state.is_locked(at_time=now):
        return True, state
    return False, state


def record_login_failure(identifier, request=None, at_time=None):
    """
    Atomically records a failed authentication attempt.
    If the account reaches 5 consecutive failed attempts, locks it for 15 minutes.
    If the account was already locked, records the locked attempt without disclosing lockout.
    """
    key, user = resolve_account_key_and_user(identifier)
    now = at_time or timezone.now()
    client_ip = extract_client_ip(request) if request else None

    def _execute():
        with transaction.atomic():
            state, _ = LoginSecurityState.objects.select_for_update().get_or_create(
                identifier=key,
                defaults={'user': user, 'failed_attempts': 0}
            )
            if user and not state.user:
                state.user = user

            if state.is_locked(at_time=now):
                # Account is under active lockout
                record_security_event(
                    action='login_attempt_account_locked',
                    request=request,
                    actor=user,
                    actor_label=identifier,
                    ip_address=client_ip,
                    target_type='account',
                    target_id=str(user.pk) if user else key,
                    details={'canonical_key': key, 'remaining_seconds': state.get_remaining_lockout_seconds(now)},
                    severity='WARNING',
                )
                return True, state

            # If previous lockout period has elapsed, restart streak
            if state.lockout_until and now >= state.lockout_until:
                state.failed_attempts = 1
                state.lockout_until = None
            else:
                state.failed_attempts += 1

            state.last_failed_at = now

            if state.failed_attempts >= LOCKOUT_THRESHOLD:
                state.lockout_until = now + timedelta(seconds=LOCKOUT_DURATION_SECONDS)
                state.save()
                record_security_event(
                    action='account_locked',
                    request=request,
                    actor=user,
                    actor_label=identifier,
                    ip_address=client_ip,
                    target_type='account',
                    target_id=str(user.pk) if user else key,
                    details={
                        'canonical_key': key,
                        'failed_attempts': state.failed_attempts,
                        'lockout_duration_seconds': LOCKOUT_DURATION_SECONDS,
                    },
                    severity='WARNING',
                )
                return True, state

            state.save()
            record_security_event(
                action='login_failed',
                request=request,
                actor=user,
                actor_label=identifier,
                ip_address=client_ip,
                target_type='account',
                target_id=str(user.pk) if user else key,
                details={'canonical_key': key, 'consecutive_failed': state.failed_attempts},
                severity='WARNING',
            )
            return False, state

    return with_db_retry(_execute)


def record_login_success(user, request=None, at_time=None):
    """
    Atomically resets failed attempt counters upon successful authentication.
    """
    key = f"user:{user.pk}"
    now = at_time or timezone.now()
    client_ip = extract_client_ip(request) if request else None

    def _execute():
        with transaction.atomic():
            LoginSecurityState.objects.filter(identifier=key).update(
                failed_attempts=0,
                lockout_until=None,
                last_success_at=now,
            )

    with_db_retry(_execute)

    record_security_event(
        action='login_success',
        request=request,
        actor=user,
        actor_label=user.username,
        ip_address=client_ip,
        target_type='account',
        target_id=str(user.pk),
        details={'canonical_key': key, 'role': user.role},
        severity='INFO',
    )


def check_ip_rate_limit(request, at_time=None):
    """
    Evaluates sliding-window IP rate limit (at most 10 login requests per minute).
    Returns (is_limited: bool, count: int).
    """
    client_ip = extract_client_ip(request)
    if not client_ip:
        return False, 0

    now = at_time or timezone.now()
    window_start = now - timedelta(seconds=IP_RATE_LIMIT_WINDOW_SECONDS)

    def _execute():
        return LoginRateLimitRecord.objects.filter(
            ip_address=client_ip,
            timestamp__gte=window_start
        ).count()

    count = with_db_retry(_execute)
    is_limited = count >= IP_RATE_LIMIT_MAX_REQUESTS
    return is_limited, count


def record_ip_login_request(request, at_time=None):
    """
    Records an incoming login attempt timestamp against the source IP
    and prunes records older than 5 minutes.
    """
    client_ip = extract_client_ip(request)
    if not client_ip:
        return

    now = at_time or timezone.now()

    def _execute():
        LoginRateLimitRecord.objects.create(ip_address=client_ip, timestamp=now)
        # Prune old records to maintain bounded table size safely
        try:
            LoginRateLimitRecord.objects.filter(
                timestamp__lt=now - timedelta(minutes=5)
            ).delete()
        except OperationalError:
            pass

    with_db_retry(_execute)
