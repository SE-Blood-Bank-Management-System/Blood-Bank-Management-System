# Password Reset, Login Lockout, and Secure Deployment Settings

**Document ID**: BBMS-DOC-045<br>
**SRS Requirements**: BBMS-F-005, BBMS-SR-006, BBMS-SR-007, BBMS-SR-008, BBMS-NF-006<br>
**Test Plan Cases**: TC-AUTH-01/02, TC-SEC-06, TC-SEC-07, TC-SEC-08, TC-NF-02<br>
**Related Issue**: #45 (Consolidates Sprint 2 issues #46 and #48)

---

## 1. Executive Summary

Issue #45 establishes robust access recovery, defense against brute-force attacks, tamper-evident audit logging, and production-ready HTTPS deployment controls for the Blood Bank Management System (BBMS).

### Core Capabilities Delivered:
1. **Time-Limited, Single-Use Password Reset (BBMS-F-005)**:
   - Django cryptographic token generator with a 15-minute validity window (`PASSWORD_RESET_TIMEOUT = 900`).
   - Tokens invalidate immediately upon use (hash changes with password update).
   - Generic enumeration-proof responses for both existing and unknown emails.
   - Environment-configured SMTP delivery demonstrated over real TCP socket connections.
   - Immediate unlocking of locked accounts upon successful reset.
2. **Account Lockout & Brute-Force Protection (BBMS-SR-007, TC-SEC-07)**:
   - 15-minute account lockout after 5 consecutive failed login attempts.
   - Normalization of username and email aliases to a canonical account identity (`user:<pk>`), preventing counter evasion.
   - Shared atomic database state (`LoginSecurityState`) safe across multi-process WSGI deployments without relying on per-process in-memory dictionaries.
   - Consistent protection across HTML sign-in (`/accounts/login/`) and Django Admin (`/admin/login/`).
3. **Sliding-Window IP Rate Limiting (BBMS-SR-007, TC-SEC-07)**:
   - Enforces at most 10 login requests per minute per source IP via `LoginProtectionMiddleware`.
   - Returns HTTP 429 Too Many Requests with `Retry-After: 60` header.
   - Sliding 60-second window in `LoginRateLimitRecord`.
4. **Trusted Proxy Boundary (BBMS-SR-007, BBMS-SR-008)**:
   - Peer IP (`REMOTE_ADDR`) is authoritatively used unless the direct connection originates from an explicitly configured trusted proxy (`BBMS_TRUSTED_PROXIES`).
   - Prevents header spoofing via untrusted `X-Forwarded-For`.
5. **Central Audit Service & Timestamped Logging (BBMS-SR-008, TC-SEC-08)**:
   - Append-only, tamper-evident `SecurityAuditEvent` model (updates and deletions strictly blocked).
   - Automated scrubbing of passwords, tokens, and secrets from audit details and logs.
   - Timestamped logging configuration (`%(asctime)s [%(levelname)s] [%(name)s] %(message)s`).
   - Unhandled 500 exceptions logged with stack traces on server while clients receive clean generic error pages (`templates/500.html`).
6. **Production Deployment & HTTPS Acceptance (BBMS-NF-006, TC-NF-02)**:
   - Environment-driven `DEBUG=False`, mandatory `BBMS_SECRET_KEY`, `ALLOWED_HOSTS`, and `CSRF_TRUSTED_ORIGINS`.
   - Automated HTTPS redirect (`SECURE_SSL_REDIRECT`), HSTS headers (`SECURE_HSTS_SECONDS`), and Secure/HttpOnly session cookies.

---

## 2. Password Reset Workflow (BBMS-F-005)

### Workflow Endpoints
| URL Route | View | Description |
| :--- | :--- | :--- |
| `GET/POST /accounts/password-reset/` | `accounts:password_reset` | Request screen: accepts email, triggers time-limited token generation and SMTP message. |
| `GET /accounts/password-reset/done/` | `accounts:password_reset_done` | Generic acknowledgment screen. Never confirms or denies account existence. |
| `GET/POST /accounts/reset/<uidb64>/<token>/` | `accounts:password_reset_confirm` | Reset screen: validates single-use token; renders password change form or invalid/expired alert. |
| `GET /accounts/reset/done/` | `accounts:password_reset_complete` | Success screen: confirms reset, links to sign-in. |

### Security Guarantees:
- **Enumeration Prevention**: Submitting an unregistered or inactive email returns the identical success redirection and done page. Audit records `password_reset_request_unknown` without leaking user data.
- **Single-Use Replay Protection**: Django's token includes the user's password hash in the HMAC. Saving a new password changes the hash, instantly rendering the token invalid for any replay attempt.
- **Time-Limited Validity**: The link expires after 900 seconds (15 minutes). Requests after 15 minutes are rejected with `validlink = False`.
- **Lockout Recovery**: When a user successfully resets their password, any active account lockout is cleared (`LoginSecurityState.objects.filter(user=user).update(failed_attempts=0, lockout_until=None)`), allowing immediate login.

---

## 3. Account Lockout & Rate Limiting Controls (BBMS-SR-007)

### Specification Compliance Matrix
| Control | Specification | Implementation Reference |
| :--- | :--- | :--- |
| **Lockout Threshold** | 5 consecutive failed login attempts | `accounts.security.LOCKOUT_THRESHOLD = 5` |
| **Lockout Duration** | 15 minutes (900 seconds) | `accounts.security.LOCKOUT_DURATION_SECONDS = 900` |
| **IP Rate Limit** | $\le 10$ login requests per minute per IP | `accounts.security.IP_RATE_LIMIT_MAX_REQUESTS = 10` |
| **Rate Limit Window** | 60-second sliding window | `accounts.security.IP_RATE_LIMIT_WINDOW_SECONDS = 60` |
| **Alias Normalization** | Identical counter for username & email | `resolve_account_key_and_user()` maps to `user:<pk>` |
| **Counter Reset** | Reset counter to 0 on valid authentication | `record_login_success()` clears counter and lockout |
| **Protection Scope** | HTML login, JSON login, Django Admin | `LoginProtectionMiddleware` + `EmailOrUsernameModelBackend` |
| **Proxy Boundary** | Trust forwarded IP only behind trusted proxy | `extract_client_ip()` checks `BBMS_TRUSTED_PROXIES` |

### Post-Lockout Behavior
1. **During 15-Minute Lockout Window**:
   - Every attempt (even with valid password) fails immediately.
   - Authentication backend avoids password hashing and timing leaks.
   - Form returns standard generic failure ("Invalid email/username or password.").
   - Audit event `login_attempt_account_locked` is recorded with remaining seconds.
2. **After Lockout Expiration**:
   - If user supplies valid credentials: authentication succeeds, counter resets to 0.
   - If user supplies invalid credentials: a fresh streak starts (`failed_attempts = 1`), giving 4 more attempts before re-locking.

---

## 4. Reverse Proxy & Trusted Boundary Configuration

To prevent attackers from bypassing IP rate limiting by spoofing headers like `X-Forwarded-For: 1.2.3.4`, BBMS strictly evaluates proxy headers:

```
                      +-------------------+
                      |   Client Browser  | (IP: 203.0.113.195)
                      +---------+---------+
                                |
                                v
               +---------------------------------+
               |  Reverse Proxy (Nginx / ALB)    | (IP: 10.0.0.1)
               |  Adds X-Forwarded-For:          |
               |  203.0.113.195                  |
               +----------------+----------------+
                                |
                                v
            +---------------------------------------+
            |      BBMS Application Server          |
            |                                       |
            |  REMOTE_ADDR == 10.0.0.1?             |
            |  - In BBMS_TRUSTED_PROXIES:           |
            |    Trust XFF client IP: 203.0.113.195 |
            |  - NOT in BBMS_TRUSTED_PROXIES:       |
            |    Ignore XFF, use REMOTE_ADDR        |
            +---------------------------------------+
```

---

## 5. Environment Variables & Production Deployment Reference

| Variable | Default (Dev) | Production Value | Purpose |
| :--- | :--- | :--- | :--- |
| `BBMS_DEBUG` | `True` | `False` | Disables debug mode and technical tracebacks |
| `BBMS_SECRET_KEY` | *(insecure dev key)* | `*REQUIRED*` | Cryptographic signing secret (enforces check on boot) |
| `BBMS_ALLOWED_HOSTS` | `127.0.0.1,localhost` | `bbms.yourdomain.org` | HTTP Host header validation |
| `BBMS_CSRF_TRUSTED_ORIGINS`| *(empty)* | `https://bbms.yourdomain.org` | CSRF origin whitelist |
| `BBMS_SECURE_SSL_REDIRECT` | `0` | `1` | Enforces 301 redirect from HTTP to HTTPS |
| `BBMS_SECURE_HSTS_SECONDS` | `0` | `31536000` | HTTP Strict Transport Security (1 year) |
| `BBMS_SECURE_COOKIES` | `1` | `1` | Secure flag on session and CSRF cookies |
| `BBMS_TRUSTED_PROXIES` | *(empty)* | `127.0.0.1,10.0.0.1` | Reverse proxy IP whitelist for XFF headers |
| `PASSWORD_RESET_TIMEOUT` | `900` | `900` | Reset token lifetime in seconds (15 min) |
| `EMAIL_BACKEND` | `smtp.EmailBackend` | `smtp.EmailBackend` | Django mail backend |
| `EMAIL_HOST` | `localhost` | `smtp.sendgrid.net` | SMTP server hostname |
| `EMAIL_PORT` | `587` | `587` | SMTP port |
| `EMAIL_HOST_USER` | *(empty)* | `apikey` | SMTP username |
| `EMAIL_HOST_PASSWORD` | *(empty)* | *(production credential)* | SMTP password |
| `EMAIL_USE_TLS` | `0` | `1` | Enforce STARTTLS for email delivery |
| `DEFAULT_FROM_EMAIL` | `noreply@bbms.local` | `noreply@bbms.org` | Sender address on outgoing notification emails |

---

## 6. Concrete HTTPS Acceptance Setup

### Example Nginx Reverse Proxy Configuration (TLS 1.2/1.3)

```nginx
# /etc/nginx/sites-available/bbms
server {
    listen 80;
    server_name bbms.hospital.local;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl http2;
    server_name bbms.hospital.local;

    ssl_certificate /etc/ssl/certs/bbms.crt;
    ssl_certificate_key /etc/ssl/private/bbms.key;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;

    location /static/ {
        alias /var/www/bbms/staticfiles/;
    }

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
    }
}
```

### Starting the Production App with Environment Secrets:
```bash
export BBMS_DEBUG=0
export BBMS_SECRET_KEY="c49f82d...your-secure-random-key..."
export BBMS_ALLOWED_HOSTS="bbms.hospital.local,127.0.0.1"
export BBMS_CSRF_TRUSTED_ORIGINS="https://bbms.hospital.local"
export BBMS_SECURE_SSL_REDIRECT=1
export BBMS_TRUSTED_PROXIES="127.0.0.1"
export BBMS_SECURE_COOKIES=1
export EMAIL_HOST="smtp.hospital.local"
export EMAIL_PORT=587
export EMAIL_USE_TLS=1

gunicorn bbms.wsgi:application --bind 127.0.0.1:8000 --workers 4
```

---

## 7. Retained Interface Deviations & Scope Notes

- **Authentication Protocol**: Access control uses Django standard session cookies with server-side rolling expiration and CSRF protection. Third-party auth tokens (e.g. JWT) are retained outside this scope per the Issue #45 commitment.
- **Local HTTP Development Override**: `BBMS_SECURE_COOKIES=0` is retained strictly for local development and non-TLS evaluation. It is never used in production.
