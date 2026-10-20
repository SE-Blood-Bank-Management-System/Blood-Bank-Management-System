# Donor registration (Issue #2)

Registration is available to logged-out visitors at `/accounts/register/donor/`.
The existing `accounts.User` is both the account and donor profile: first/last
name, date of birth, gender, phone and optional self-reported blood group are
stored there. There is no separate DonorProfile model and no schema change.

The existing server-side age calculation rejects applicants before their 18th
birthday. Email is normalized and checked case-insensitively. Registration
rejects email addresses used as legacy usernames to avoid ambiguous login with
the existing email-or-username backend. Emails longer than the username field
use a generated internal username and remain usable for email login.

Password validation now receives the applicant's populated user instance.
Passwords are hashed with Django's configured hasher. The form saves atomically,
and a competing registration claiming the same email produces an email error.
Invalid submissions preserve non-password values and show field-specific errors.
The existing automatic login and donor-dashboard redirect remain in place.

## Verification

- 15 registration regression tests pass with the project's default password settings.
- All 98 tests pass with a temporary PBKDF2 hasher using 1,000 iterations for test speed.
  This override is process-local and is not included in application settings.
- `python manage.py check` passes.
- `python manage.py makemigrations --check --dry-run` reports no changes.
- `python -m flake8 .` and `git diff --check` pass.

Run registration tests: `python manage.py test accounts.test_registration`.
Run the normal full suite: `python manage.py test`.
The normal full-suite and baseline runs were interrupted because hashing was
slow in this environment; their complete results are not claimed here.

Coverage includes birthday boundaries, future/invalid dates, required fields,
invalid input, duplicate and racing email claims, profile fields, password
validation and hashing, privilege injection, transactional rollback, long email
login, username collisions, CSRF and authenticated visitor handling.

## Suggested pull request

Title: Complete donor registration validation and error handling

The existing donor registration loses entered values on validation failure and
can accept passwords similar to the applicant's details. This change validates
passwords against the populated user, validates contact numbers, preserves form
values, and shows inline errors. It also saves accounts atomically and handles
email races and username collisions without duplicating the user/profile model.

Validation: 15 registration tests with default password settings; 98 full-suite
tests with a temporary reduced-iteration PBKDF2 hasher; Django checks, migration
drift check, flake8 and diff whitespace checks pass.

Closes #2

A teammate should review the PR before merge. Publishing the branch, creating
a PR, requesting review and changing the project board have not been performed.
