# Issue #7: Donor profile, history and next eligible date

## Requirements and scope

This implements SRS BBMS-F-006, F-007 and F-008 and Test Plan TC-DNR-01.
It uses the existing accounts.User and inventory.BloodUnit models; there is no
second donor profile model, schema migration or new dependency.

- Donors view registered details and update phone, address and self-reported
  blood group on /accounts/profile/.
- Dashboard and history now show recorded collections rather than placeholders.
- History shows collection date, location, Bag ID and volume, newest first.
- The next eligible donation date uses a configurable 90-day default interval.
- Donors can only see their own data. Authorized STAFF and ADMIN users can
  review a selected donor through read-only profile/history pages.

## Collection and interval rules

A completed donation is represented by a top-level BloodUnit collection record.
The latest record dated at or before the current time anchors the interval.
Derived components with a parent_unit are excluded so separation does not count
as another donation. Future-dated records and other donors' records are excluded.

Collection completion is distinct from blood-unit availability: a later failed
serology result, disposal, expiry or allocation does not undo the physical
collection or shorten the donor's waiting interval. This interpretation follows
the existing record_collection method's completed-collection semantics.

DONATION_MIN_INTERVAL_DAYS in bbms/settings.py defaults to 90. Set it to another
positive integer to change the project interval. Invalid configuration fails
explicitly rather than silently allowing an unsafe or undefined interval.
The next date is the last collection's local calendar date plus that interval;
calendar dates use Django's configured TIME_ZONE. The interval is met on the
calculated date, including the exact boundary.

A first-time donor has no historical interval deadline: HTML explains the empty
history, and the API returns null for next_eligible_date. This is distinct from
passing medical screening. The dashboard labels medical screening separately.
This issue displays the interval; it does not replace Issue #9's booking rules.

## Pages and access

| URL | Access |
| --- | --- |
| /accounts/profile/ | Current user's profile; only permitted fields editable |
| /donors/dashboard/ | Existing donor/admin dashboard with real totals and recent history |
| /donors/history/ | Current donor's paginated history |
| /donors/<donor_id>/profile/ | Donor's own profile or read-only review by STAFF/ADMIN |
| /donors/<donor_id>/history/ | Donor's own history or read-only review by STAFF/ADMIN |

The staff blood-unit detail page links to its donor's profile. Targeted donor
pages accept safe read methods only. Another donor's target ID is rejected
before looking it up; missing IDs return 404 only to authorized reviewers.
History pages show 25 collections per page. Dashboards show the latest five.
Private pages and API responses use no-store caching headers.

## API contract (SAD 4.3)

| Method | Endpoint | Purpose |
| --- | --- | --- |
| GET / PUT | /api/donors/me | Read or update the authenticated donor's profile |
| GET | /api/donors/me/donations | Paginated collection history, date/location/Bag ID/volume |
| GET | /api/donors/me/eligibility | Next date, interval setting and separate screening status |

PUT accepts an application/json object containing only phone, address and/or
blood_group strings; omitted fields retain their current values. Use empty
strings to clear optional values. Unknown fields, privileged fields, invalid
phone/blood-group values, malformed JSON and non-string values are rejected.

The profile GET issues a CSRF cookie. A same-origin client must send its value
in X-CSRFToken for PUT. Standard session authentication and CSRF middleware apply.
API outputs use explicit field lists; password hashes, account permissions,
serology details and collection notes are not included in donor history.
The eligibility API's is_eligible combines the interval with the recorded medical
screening result; can_donate_by_interval reports the interval alone.

## Verification and review

The feature adds 30 tests covering the interval boundary, configuration, time
zone, component/future exclusions, disposal, profile display and updates,
lab/self-reported group isolation, privacy, authorized staff review, empty
states, pagination, JSON errors, CSRF, escaped markup and screening separation.

```bash
python manage.py test donors.test_history_rules donors.test_profile_views donors.test_profile_api --parallel 4
python manage.py test --parallel 4
python -m flake8 .
python manage.py check
python manage.py makemigrations --check --dry-run
git diff --check
```

For manual review, open a donor's profile, edit allowed fields, view their history,
and compare the next date with the latest collection plus the configured interval.
Sign in as another donor to confirm access is denied. Staff can follow the donor
link on a blood-unit detail page but cannot edit the selected donor's profile.
For local HTTP development use the existing BBMS_SECURE_COOKIES=0 override;
HTTPS environments must keep Secure cookies enabled.
