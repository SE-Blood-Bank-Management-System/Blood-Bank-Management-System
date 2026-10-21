# Issue #3: Login, logout and secure sessions

## Scope and requirements

This implements Issue #3's Week 1 acceptance criteria using the existing custom
`accounts.User`, authentication backend and Django database-backed sessions.

| Requirement | Implementation / verification |
| --- | --- |
| F-004 / SR-001: email and password authentication | Case-insensitive email and existing username login; invalid credentials rejected |
| Role-directed navigation | Donors: donor dashboard; Staff/Admin: inventory dashboard; Hospital: existing home page |
| SR-002: secure password storage | Existing Django password hashers retained without changing their work factor |
| SR-003: protected pages | Existing RBAC/login decorators; anonymous HTML redirects and API 401 responses |
| SR-006 / TC-SEC-06: cookie security | Secure and HttpOnly session cookie, SameSite=Lax, explicit 1,800-second expiry |
| SR-006: inactivity expiry | Server-side session expiry renewed on each request with SESSION_SAVE_EVERY_REQUEST |
| SR-006: logout invalidation | CSRF-protected POST flushes the database session; replaying its old cookie fails |

Tests cover required/incorrect credentials, case-insensitive email, all role
destinations, safe return URLs, rejection of external URLs and HTTPS downgrades,
inactive/unapproved accounts, long emails, ambiguous identifiers, session-key
rotation, cookie flags, activity renewal, expiration, CSRF and logout replay.

Account lockout, IP rate limiting (SR-007), and the system-wide security audit
trail (SR-008) are outside the explicitly agreed Issue #3 scope. This document
does not claim that those broader SRS requirements are complete.

## Session and login behavior

No additional session token or user model is introduced. Django's session
middleware stores a rolling server expiry 30 minutes after each active request.
An expired session cannot read protected HTML or JSON resources. Login rotates
an existing anonymous session key. Logout accepts POST only and invalidates the
old session on the server, rather than merely removing a browser cookie.
The login response is marked non-cacheable. Login errors retain the identifier
and safe return destination; passwords are never rendered back into the form.

The custom backend rejects ambiguous username/email matches. A second fallback
backend was removed because it could authenticate a username after the custom
backend rejected the same ambiguous identifier. The custom backend inherits
Django's ModelBackend permissions, so existing admin/RBAC behavior is retained.

## Running locally versus HTTPS

Cookies default to Secure, including when DEBUG=True. An HTTPS environment must
leave BBMS_SECURE_COOKIES unset or set it to 1. Configure TLS on the hosting layer.
This change does not set up a TLS certificate or a production deployment.

For the local HTTP development server only, run:

```powershell
$env:BBMS_SECURE_COOKIES = "0"
python manage.py runserver
```

This deliberately switches off the Secure flag for both session and CSRF cookies
in that process; it does not disable CSRF validation, HttpOnly or SameSite.
Do not use the local HTTP override for a deployed environment.

## Acceptance review

1. Sign in using a registered donor's email and password; verify the dashboard.
2. Submit incorrect credentials and blank fields; verify no session is granted.
3. Open a protected URL while logged out; verify the login redirect.
4. In an HTTPS environment, inspect the session cookie's Secure, HttpOnly,
   SameSite=Lax and 30-minute Max-Age attributes.
5. Use either Logout button; verify the redirect and denial of protected access.
6. Use the expiry/renewal tests to simulate inactivity without a 30-minute wait.
7. Confirm staff/admin navigation and account approval restrictions still work.

Run automated verification with normal application password settings:

```bash
python manage.py test
python manage.py check
python manage.py makemigrations --check --dry-run
python -m flake8 .
git diff --check
```

The focused regression command is:
`python manage.py test accounts.test_login accounts.test_sessions`.
No migration or third-party authentication package is required.
