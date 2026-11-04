# Deliverable 3 — Abhinav: updated test cases

Owner: **Abhinav K (@abhinavk0006)**. Prepared: **4 November 2026**.
Baseline: main `076935a`. Document ID: **BBMS-D3-AK-TC-001**, version 1.0.
This is the final testing/documentation deliverable, not a new sprint.

## Scope and ownership

This owner-specific addendum expands the original Deliverable 1 STP §13.1 cases
to match the implemented application. The original PDF remains the plan baseline.
`-AK-xx` suffixes identify executable subcases without replacing team STP IDs.
GitHub assigned issues establish implementation ownership:

| Issues | Owner contribution | STP parents |
| --- | --- | --- |
| #2, #3 | Donor registration, login/logout and secure sessions | TC-AUTH-01; logout portion of TC-AUTH-02; TC-SEC-06 |
| #7 | Donor profile, history and next eligible date | TC-DNR-01 |
| #14 | Quarantine list and structured status-change history | TC-QNT-01 |
| #30 (includes former #31) | Hospital requisitions, review and STAT queue | TC-REQ-01/02/03 |
| #32 | Hospital tracking and delivery confirmation | TC-DEL-01; TC-REQ-02 |
| #49 | Integrated workflow and NFR coordination | Integration subcase and TC-NF-01–06 follow-up matrix |

Password reset/lockout (#45), component separation (#35), cross-matching (#36),
allocation/dispatch (#37), reports (#42) and central audit (#47) stay with their
feature owners. They are dependencies in integration tests, not reassigned work.
Registration, donor profile and quarantine remain Abhinav's contributions even
where a separate draft team document labels them differently. Shared security
cases are split by functionality rather than claiming ownership of all security.

## Changes from the original cases

- Authentication and registration use implemented HTML forms; the planned
  standalone `/api/auth/*` adapters are still absent.
- Donor profile is held in `accounts.User`. Self-reported group changes cannot
  overwrite laboratory unit groups. Component children are not extra donations.
- The default minimum interval is configurable (90 days); interval eligibility
  and medical screening are separate conditions, not clinical clearance.
- Status history uses structured append-only records; re-entry to quarantine
  resets its elapsed-time clock. Central audit is a separate shared dependency.
- STAT alerts poll every five seconds; passive polls must not prolong idle login.
- Requisition review/priority and delivery use version checks and atomic services.
  Fulfilment is dispatch-based; receiving a partial shipment cannot fulfil a request.
- Delivery API IDs identify persisted fulfilment records, not Bag IDs. Donor APIs
  retain their existing slashless routes. See [actual interfaces](../../sprint2/interfaces.md).

## Test setup and execution rules

Use a migrated, isolated test database and synthetic records only. Django test
runner creates/destroys its test database. Do not point it at production data.
Manual equivalents may use abhinav/navaneeth donors, uttam staff and akshay admin
with `example.test` email addresses; include two separately owned hospital accounts.
Automated suites retain their existing deterministic fixture names and clocks.

Each case below has independent preconditions; reset state before the next case.
For HTML/API checks, inspect status/body AND reload affected database records.
For denied writes, check there is no partial account, status, event or receipt.
Server-side tests simulate HTTPS where needed; they do not validate a live TLS
certificate. Fault injection is confined to tests. SQLite tests do not establish
production row-locking or simultaneous multi-user database behaviour.

The CSV contains the same case IDs, steps, expected results and exact runnable
test labels. The separate execution record distinguishes this run from manual
checks and prior Sprint 2 evidence. Test-method counts are not assertion counts.

### TC-AUTH-01-AK-01 — Adult registration and password storage

- **Traceability:** TC-AUTH-01; #2; BBMS-F-001; BBMS-SR-002.
- **Priority:** High. **Method:** automated regression with the manual/service procedure below.
- **Preconditions/data:** Public visitor; unique synthetic email; adult donor details and a strong password.
- **Steps:** Submit the donor registration form. Read the saved user and resulting session.
- **Expected:** One DONOR account contains the submitted profile, password verifies as a hash rather than plaintext, and the donor dashboard is reached.
- **Runnable test:** `accounts.test_registration.DonorRegistrationTests.test_registration_creates_existing_user_profile_and_hashes_password`.
- **Actual result/status:** see [execution record](execution.md) and CSV.

### TC-AUTH-01-AK-02 — Age boundary and future birth dates

- **Traceability:** TC-AUTH-01; #2; BBMS-F-002.
- **Priority:** High. **Method:** automated regression with the manual/service procedure below.
- **Preconditions/data:** Freeze today to 20 October 2026; DOBs 20/21/19 October 2008 and 1 January 2027.
- **Steps:** Validate a fresh registration form for each DOB.
- **Expected:** Exactly 18 and older are accepted; one day under 18 and future birth dates are rejected.
- **Runnable test:** `accounts.test_registration.DonorRegistrationTests.test_birthday_boundary_and_future_dates`.
- **Actual result/status:** see [execution record](execution.md) and CSV.

### TC-AUTH-01-AK-03 — Case-insensitive duplicate email

- **Traceability:** TC-AUTH-01; #2; BBMS-F-003.
- **Priority:** High. **Method:** automated regression with the manual/service procedure below.
- **Preconditions/data:** Existing jane@example.com; repeat as whitespace-padded JANE@EXAMPLE.COM.
- **Steps:** Submit the otherwise valid registration and inspect the email error and user count.
- **Expected:** A field error is shown and no second account is created.
- **Runnable test:** `accounts.test_registration.DonorRegistrationTests.test_case_insensitive_duplicate_email_rejected`.
- **Actual result/status:** see [execution record](execution.md) and CSV.

### TC-AUTH-01-AK-04 — Required registration fields

- **Traceability:** TC-AUTH-01; #2; BBMS-F-001; BBMS-NF-009.
- **Priority:** High. **Method:** automated regression with the manual/service procedure below.
- **Preconditions/data:** Valid adult data; independently blank first name, last name, email, DOB, phone, gender and password.
- **Steps:** Submit each missing-field variant and inspect form errors and database count.
- **Expected:** Each missing required value has a field error; no account is persisted.
- **Runnable test:** `accounts.test_registration.DonorRegistrationTests.test_required_fields_rejected_without_creating_user`.
- **Actual result/status:** see [execution record](execution.md) and CSV.

### TC-AUTH-01-AK-05 — Invalid registration values

- **Traceability:** TC-AUTH-01; #2; BBMS-F-001; BBMS-SR-005.
- **Priority:** High. **Method:** automated regression with the manual/service procedure below.
- **Preconditions/data:** Otherwise valid data; invalid email/DOB/gender, blood group C+, and non-phone text.
- **Steps:** Submit each invalid value independently.
- **Expected:** Invalid choices and contact values are rejected without creating a user.
- **Runnable test:** `accounts.test_registration.DonorRegistrationTests.test_invalid_choices_and_contact_rejected`.
- **Actual result/status:** see [execution record](execution.md) and CSV.

### TC-AUTH-01-AK-06 — Registration cannot grant privileges

- **Traceability:** TC-AUTH-01; #2; BBMS-SR-003.
- **Priority:** High. **Method:** automated regression with the manual/service procedure below.
- **Preconditions/data:** Public donor registration with extra role=ADMIN, is_staff=true and is_superuser=true.
- **Steps:** Submit and reload the stored account.
- **Expected:** Stored role remains DONOR and neither staff nor superuser permission is granted.
- **Runnable test:** `accounts.test_registration.DonorRegistrationTests.test_privileged_fields_cannot_be_submitted`.
- **Actual result/status:** see [execution record](execution.md) and CSV.

### TC-AUTH-01-AK-07 — Safe inline registration errors

- **Traceability:** TC-AUTH-01; #2; BBMS-NF-009; BBMS-SR-002.
- **Priority:** High. **Method:** automated regression with the manual/service procedure below.
- **Preconditions/data:** Valid data except an under-age DOB.
- **Steps:** Submit and inspect the returned form HTML.
- **Expected:** Non-secret fields are preserved, the DOB error is associated with its field, and the password is not echoed.
- **Runnable test:** `accounts.test_registration.DonorRegistrationTests.test_validation_preserves_values_and_shows_inline_errors_but_no_password`.
- **Actual result/status:** see [execution record](execution.md) and CSV.

### TC-AUTH-01-AK-08 — Registration rollback after insert failure

- **Traceability:** TC-AUTH-01; #2; BBMS-F-001.
- **Priority:** High. **Method:** automated regression with the manual/service procedure below.
- **Preconditions/data:** Valid form; inject a failure immediately after User.save inserts the account.
- **Steps:** Save the form, catch the simulated exception and query users.
- **Expected:** The account insert is rolled back; no partial account remains.
- **Runnable test:** `accounts.test_registration.DonorRegistrationTests.test_failure_during_save_rolls_back_account`.
- **Actual result/status:** see [execution record](execution.md) and CSV.

### TC-AUTH-01-AK-09 — Email and username authentication

- **Traceability:** TC-AUTH-01; #3; BBMS-F-004; BBMS-SR-001.
- **Priority:** High. **Method:** automated regression with the manual/service procedure below.
- **Preconditions/data:** Active approved donor with known password and email.
- **Steps:** Log in using mixed-case email, then log out and log in using username.
- **Expected:** Both supported identifiers authenticate the correct account.
- **Runnable test:** `accounts.test_login.LoginSecurityTests.test_email_is_case_insensitive_and_username_still_works`.
- **Actual result/status:** see [execution record](execution.md) and CSV.

### TC-AUTH-01-AK-10 — Invalid credentials

- **Traceability:** TC-AUTH-01; #3; BBMS-F-004; BBMS-SR-001.
- **Priority:** High. **Method:** automated regression with the manual/service procedure below.
- **Preconditions/data:** Registered donor; wrong password and missing credential variants.
- **Steps:** Submit each invalid login and inspect session authentication state.
- **Expected:** Login fails without an authenticated session.
- **Runnable test:** `accounts.test_login.LoginSecurityTests.test_invalid_credentials_and_required_fields_do_not_authenticate`.
- **Actual result/status:** see [execution record](execution.md) and CSV.

### TC-AUTH-01-AK-11 — Role destinations

- **Traceability:** TC-AUTH-01; #3; BBMS-F-004; BBMS-F-041.
- **Priority:** High. **Method:** automated regression with the manual/service procedure below.
- **Preconditions/data:** Active approved DONOR, HOSPITAL, STAFF and ADMIN accounts.
- **Steps:** Authenticate separately with each role.
- **Expected:** Each account reaches its configured role destination.
- **Runnable test:** `accounts.test_login.LoginSecurityTests.test_all_roles_reach_the_existing_role_destination`.
- **Actual result/status:** see [execution record](execution.md) and CSV.

### TC-AUTH-01-AK-12 — Inactive and unapproved accounts

- **Traceability:** TC-AUTH-01; #3; BBMS-SR-001; BBMS-SR-003.
- **Priority:** High. **Method:** automated regression with the manual/service procedure below.
- **Preconditions/data:** Known correct donor credentials; independently disable is_active and is_approved.
- **Steps:** Attempt login for each disabled state.
- **Expected:** The response does not establish an authenticated session.
- **Runnable test:** `accounts.test_login.LoginSecurityTests.test_inactive_and_unapproved_users_cannot_log_in`.
- **Actual result/status:** see [execution record](execution.md) and CSV.

### TC-AUTH-01-AK-13 — Unsafe return URLs

- **Traceability:** TC-AUTH-01; #3; BBMS-SR-001.
- **Priority:** High. **Method:** automated regression with the manual/service procedure below.
- **Preconditions/data:** Valid credentials; external, scheme-relative, javascript and insecure HTTP next URLs.
- **Steps:** Log in with each next target.
- **Expected:** Unsafe targets are ignored and the permitted role destination is used.
- **Runnable test:** `accounts.test_login.LoginSecurityTests.test_unsafe_next_urls_fall_back_to_role_destination`.
- **Actual result/status:** see [execution record](execution.md) and CSV.

### TC-SEC-06-AK-01 — Secure session cookie configuration

- **Traceability:** TC-SEC-06; #3; BBMS-SR-006.
- **Priority:** High. **Method:** automated regression with the manual/service procedure below.
- **Preconditions/data:** Successful login through a simulated HTTPS Django request.
- **Steps:** Inspect the session cookie and configured lifetime.
- **Expected:** Secure and HttpOnly are true, SameSite is Lax, and explicit expiry/max-age is 1800 seconds. This does not verify deployed TLS.
- **Runnable test:** `accounts.test_sessions.SecureSessionTests.test_secure_cookie_has_explicit_expiry`.
- **Actual result/status:** see [execution record](execution.md) and CSV.

### TC-SEC-06-AK-02 — Activity renews inactivity expiry

- **Traceability:** TC-SEC-06; #3; BBMS-SR-006.
- **Priority:** High. **Method:** automated regression with the manual/service procedure below.
- **Preconditions/data:** Authenticated session with shortened stored expiry.
- **Steps:** Request an interactive protected page; reload the session expiry.
- **Expected:** The server expiry renews to approximately 30 minutes and the cookie is renewed.
- **Runnable test:** `accounts.test_sessions.SecureSessionTests.test_activity_renews_server_expiry_and_cookie`.
- **Actual result/status:** see [execution record](execution.md) and CSV.

### TC-SEC-06-AK-03 — Expired session denial

- **Traceability:** TC-SEC-06; #3; BBMS-SR-006.
- **Priority:** High. **Method:** automated regression with the manual/service procedure below.
- **Preconditions/data:** Authenticated session whose stored expiry is moved into the past.
- **Steps:** Request a protected HTML page and then a JSON-accepting protected request.
- **Expected:** HTML redirects to login, JSON receives 401, and authentication is absent.
- **Runnable test:** `accounts.test_sessions.SecureSessionTests.test_expired_session_cannot_access_protected_html_or_api`.
- **Actual result/status:** see [execution record](execution.md) and CSV.

### TC-AUTH-02-AK-01 — Logout and stale cookie replay

- **Traceability:** TC-AUTH-02; #3; BBMS-SR-006.
- **Priority:** High. **Method:** automated regression with the manual/service procedure below.
- **Preconditions/data:** Authenticated donor; retain the original session key.
- **Steps:** POST logout. Try the old key from a fresh client against a protected page.
- **Expected:** Logout deletes the stored session and replay cannot restore access. This covers the logout portion of TC-AUTH-02; reset belongs to #45.
- **Runnable test:** `accounts.test_sessions.SecureSessionTests.test_logout_flushes_session_and_old_cookie_cannot_be_replayed`.
- **Actual result/status:** see [execution record](execution.md) and CSV.

### TC-SEC-06-AK-04 — Login/logout CSRF

- **Traceability:** TC-SEC-06; #3; BBMS-SR-006; BBMS-SR-005.
- **Priority:** High. **Method:** automated regression with the manual/service procedure below.
- **Preconditions/data:** Client with CSRF enforcement enabled; HTTPS requests.
- **Steps:** POST login and logout without tokens; then submit logout with a valid token and same-origin referer.
- **Expected:** Missing tokens receive 403; a valid authenticated logout succeeds.
- **Runnable test:** `accounts.test_sessions.SecureSessionTests.test_login_and_logout_require_csrf_tokens`.
- **Actual result/status:** see [execution record](execution.md) and CSV.

### TC-SEC-06-AK-05 — Session fixation prevention

- **Traceability:** TC-SEC-06; #3; BBMS-SR-006.
- **Priority:** High. **Method:** automated regression with the manual/service procedure below.
- **Preconditions/data:** Anonymous session exists before successful authentication.
- **Steps:** Log in and compare old/new keys and persisted sessions.
- **Expected:** The key rotates and the pre-login key is deleted.
- **Runnable test:** `accounts.test_sessions.SecureSessionTests.test_login_rotates_preexisting_session_key`.
- **Actual result/status:** see [execution record](execution.md) and CSV.

### TC-DNR-01-AK-01 — Own profile and next date

- **Traceability:** TC-DNR-01; #7; BBMS-F-006; BBMS-F-008.
- **Priority:** Medium. **Method:** automated regression with the manual/service procedure below.
- **Preconditions/data:** Signed-in donor with registered profile fields and a prior collection.
- **Steps:** Open the donor profile and compare displayed details and next date to persisted data.
- **Expected:** Only the selected authorized donor profile is shown with the calculated next date.
- **Runnable test:** `donors.test_profile_views.DonorProfileViewTests.test_own_profile_displays_registered_fields_and_next_date`.
- **Actual result/status:** see [execution record](execution.md) and CSV.

### TC-DNR-01-AK-02 — Permitted profile edits preserve laboratory data

- **Traceability:** TC-DNR-01; #7; BBMS-F-006; BBMS-SR-003.
- **Priority:** Medium. **Method:** automated regression with the manual/service procedure below.
- **Preconditions/data:** Signed-in donor; donor self-reported group differs from a collected unit laboratory group.
- **Steps:** Submit permitted profile edits and reload donor and unit.
- **Expected:** Permitted profile fields change; protected fields and the laboratory blood group do not.
- **Runnable test:** `donors.test_profile_views.DonorProfileViewTests.test_updates_only_permitted_fields_and_not_laboratory_group`.
- **Actual result/status:** see [execution record](execution.md) and CSV.

### TC-DNR-01-AK-03 — Private ordered donation history

- **Traceability:** TC-DNR-01; #7; BBMS-F-007; BBMS-SR-003.
- **Priority:** Medium. **Method:** automated regression with the manual/service procedure below.
- **Preconditions/data:** Two donors with collections, including distinct Bag IDs and collection dates.
- **Steps:** Open the current donor history and inspect order and collection details.
- **Expected:** Only that donor collections appear in the expected order with relevant collection details.
- **Runnable test:** `donors.test_profile_views.DonorProfileViewTests.test_history_is_private_ordered_and_contains_collection_details`.
- **Actual result/status:** see [execution record](execution.md) and CSV.

### TC-DNR-01-AK-04 — Cross-donor profile isolation

- **Traceability:** TC-DNR-01; #7; BBMS-F-006; BBMS-SR-003.
- **Priority:** Medium. **Method:** automated regression with the manual/service procedure below.
- **Preconditions/data:** Signed-in donor; another donor ID and a missing ID.
- **Steps:** Request both IDs through donor-facing profile/history access.
- **Expected:** The donor cannot access another person data or distinguish missing accounts through the protected route.
- **Runnable test:** `donors.test_profile_views.DonorProfileViewTests.test_donor_cannot_select_another_donor_or_discover_missing_accounts`.
- **Actual result/status:** see [execution record](execution.md) and CSV.

### TC-DNR-01-AK-05 — Staff read-only donor review

- **Traceability:** TC-DNR-01; #7; BBMS-F-006; BBMS-SR-003.
- **Priority:** Medium. **Method:** automated regression with the manual/service procedure below.
- **Preconditions/data:** Existing donor and authenticated STAFF/ADMIN reviewers.
- **Steps:** Read donor details, then attempt a profile edit as the reviewer.
- **Expected:** Authorized review succeeds while editing donor-owned profile fields is denied.
- **Runnable test:** `donors.test_profile_views.DonorProfileViewTests.test_staff_and_admin_can_review_donor_details_but_cannot_edit_them`.
- **Actual result/status:** see [execution record](execution.md) and CSV.

### TC-DNR-01-AK-06 — Default interval and exact boundary

- **Traceability:** TC-DNR-01; #7; BBMS-F-008.
- **Priority:** Medium. **Method:** automated regression with the manual/service procedure below.
- **Preconditions/data:** Fixed clock; latest original collection 10 days ago, an older collection, and a separate exactly-90-day fixture.
- **Steps:** Compute donation_summary for both scenarios.
- **Expected:** Next date is latest collection plus the configured default 90 days; the exact boundary is eligible by interval.
- **Runnable test:** `donors.test_history_rules.DonationIntervalTests.test_default_interval_is_90_days_after_latest_collection`.
- **Actual result/status:** see [execution record](execution.md) and CSV.

### TC-DNR-01-AK-07 — Components are not extra donations

- **Traceability:** TC-DNR-01; #7; BBMS-F-007; BBMS-F-008.
- **Priority:** Medium. **Method:** automated regression with the manual/service procedure below.
- **Preconditions/data:** Original donation, derived component, future collection and another donor collection.
- **Steps:** Compute the donor donation summary.
- **Expected:** Only the donor original non-future collection counts toward history and interval.
- **Runnable test:** `donors.test_history_rules.DonationIntervalTests.test_future_records_components_and_other_donors_do_not_count`.
- **Actual result/status:** see [execution record](execution.md) and CSV.

### TC-DNR-01-AK-08 — Discarded collection still counts

- **Traceability:** TC-DNR-01; #7; BBMS-F-008.
- **Priority:** Medium. **Method:** automated regression with the manual/service procedure below.
- **Preconditions/data:** A recent original collection is Discarded.
- **Steps:** Calculate the donor interval summary.
- **Expected:** Discard does not undo the physical donation or reset the donor waiting interval.
- **Runnable test:** `donors.test_history_rules.DonationIntervalTests.test_discarded_collection_still_counts_as_a_donation`.
- **Actual result/status:** see [execution record](execution.md) and CSV.

### TC-DNR-01-AK-09 — Stored markup is escaped

- **Traceability:** TC-DNR-01; #7; BBMS-F-006; BBMS-SR-005.
- **Priority:** Medium. **Method:** automated regression with the manual/service procedure below.
- **Preconditions/data:** Donor profile with stored markup in a displayed field.
- **Steps:** Render the profile page and inspect response HTML.
- **Expected:** Stored markup appears as escaped text rather than executable HTML.
- **Runnable test:** `donors.test_profile_views.DonorProfileViewTests.test_profile_renders_stored_markup_as_text`.
- **Actual result/status:** see [execution record](execution.md) and CSV.

### TC-DNR-01-AK-10 — Malformed or privileged profile API edits

- **Traceability:** TC-DNR-01; #7; BBMS-F-006; BBMS-SR-005.
- **Priority:** Medium. **Method:** automated regression with the manual/service procedure below.
- **Preconditions/data:** Authenticated donor; invalid phone/group and role/id/email/password changes.
- **Steps:** PUT each invalid payload to /api/donors/me and reload the account.
- **Expected:** Each unsupported/privileged edit receives 400 and persisted identity/role/contact remain unchanged.
- **Runnable test:** `donors.test_profile_api.DonorProfileAPITests.test_invalid_fields_and_privileged_updates_are_rejected`.
- **Actual result/status:** see [execution record](execution.md) and CSV.

### TC-DNR-01-AK-11 — Interval and medical screening are distinct

- **Traceability:** TC-DNR-01; #7; BBMS-F-008; BBMS-F-009.
- **Priority:** Medium. **Method:** automated regression with the manual/service procedure below.
- **Preconditions/data:** Recent donation and Eligible medical screening; another donor without screening.
- **Steps:** Read /api/donors/me/eligibility for both donors.
- **Expected:** A passing screening does not bypass the waiting interval; absent screening does not imply overall eligibility.
- **Runnable test:** `donors.test_profile_api.DonorProfileAPITests.test_next_date_and_screening_are_distinct`.
- **Actual result/status:** see [execution record](execution.md) and CSV.

### TC-QNT-01-AK-01 — Quarantine queue and elapsed time

- **Traceability:** TC-QNT-01; #14; BBMS-F-030.
- **Priority:** High. **Method:** automated regression with the manual/service procedure below.
- **Preconditions/data:** Staff; Quarantined unit collected two days ago, Available/Discarded/expired comparison units.
- **Steps:** Open the quarantine queue.
- **Expected:** Only the quarantined unit appears, elapsed time is 2.0 days, count is one and response is no-store.
- **Runnable test:** `inventory.test_quarantine_views.QuarantineAndHistoryViewTests.test_queue_lists_only_quarantined_units_with_elapsed_time`.
- **Actual result/status:** see [execution record](execution.md) and CSV.

### TC-QNT-01-AK-02 — History survives leaving quarantine

- **Traceability:** TC-QNT-01; #14; BBMS-F-029; BBMS-F-030.
- **Priority:** High. **Method:** automated regression with the manual/service procedure below.
- **Preconditions/data:** Quarantined unit; staff changes it to Discarded with a reason.
- **Steps:** Read HTML and JSON history, then reopen the queue.
- **Expected:** Old/new states, actor, timestamp and reason remain available; the unit leaves the current quarantine queue.
- **Runnable test:** `inventory.test_quarantine_views.QuarantineAndHistoryViewTests.test_history_retains_old_states_and_staff_after_unit_leaves_quarantine`.
- **Actual result/status:** see [execution record](execution.md) and CSV.

### TC-QNT-01-AK-03 — Unsafe and expired stock exclusion

- **Traceability:** TC-QNT-01; #14; BBMS-F-028.
- **Priority:** High. **Method:** automated regression with the manual/service procedure below.
- **Preconditions/data:** One safe available B+ unit and Quarantined, Discarded and overdue units.
- **Steps:** Read public availability and staff inventory counts.
- **Expected:** Only the safe available unit contributes; public output does not expose staff identity.
- **Runnable test:** `inventory.test_quarantine_views.QuarantineAndHistoryViewTests.test_public_and_staff_availability_exclude_unsafe_and_expired_units`.
- **Actual result/status:** see [execution record](execution.md) and CSV.

### TC-QNT-01-AK-04 — Quarantine authorization

- **Traceability:** TC-QNT-01; #14; BBMS-F-030; BBMS-SR-003.
- **Priority:** High. **Method:** automated regression with the manual/service procedure below.
- **Preconditions/data:** Donor, hospital and anonymous clients.
- **Steps:** Attempt quarantine/history HTML and API reads.
- **Expected:** Donor/hospital receive 403; anonymous HTML redirects to login and anonymous API receives 401.
- **Runnable test:** `inventory.test_quarantine_views.QuarantineAndHistoryViewTests.test_unauthorized_roles_cannot_read_html_or_api`.
- **Actual result/status:** see [execution record](execution.md) and CSV.

### TC-QNT-01-AK-05 — Persisted status transition metadata

- **Traceability:** TC-QNT-01; #14; BBMS-F-029.
- **Priority:** High. **Method:** automated regression with the manual/service procedure below.
- **Preconditions/data:** Quarantined unit and authenticated staff; reason Storage issue.
- **Steps:** Save transition to Discarded and inspect StatusChange.
- **Expected:** History stores actual previous/new states, staff and server timestamp with reason; quarantine timestamp is cleared.
- **Runnable test:** `inventory.test_status_transitions.StatusTransitionTests.test_direct_change_logs_persisted_states_actor_and_time`.
- **Actual result/status:** see [execution record](execution.md) and CSV.

### TC-QNT-01-AK-06 — Re-entry resets quarantine clock

- **Traceability:** TC-QNT-01; #14; BBMS-F-030.
- **Priority:** High. **Method:** automated regression with the manual/service procedure below.
- **Preconditions/data:** Previously cleared unit; remove one required result in the controlled fixture.
- **Steps:** Re-evaluate at fixed time; inspect quarantine duration 12 hours later.
- **Expected:** Current-entry timestamp resets and duration is 0.5 days, rather than age since original collection.
- **Runnable test:** `inventory.test_status_transitions.StatusTransitionTests.test_return_to_quarantine_resets_elapsed_time`.
- **Actual result/status:** see [execution record](execution.md) and CSV.

### TC-QNT-01-AK-07 — Audit failure rolls back status and panel

- **Traceability:** TC-QNT-01; #14; BBMS-F-029.
- **Priority:** High. **Method:** automated regression with the manual/service procedure below.
- **Preconditions/data:** Quarantined unit; simulate failure writing StatusChange.
- **Steps:** Record a complete passing panel and catch the failure; reload unit and results.
- **Expected:** Status stays Quarantined, no panel results persist, and only the initial history entry remains.
- **Runnable test:** `inventory.test_status_transitions.StatusTransitionTests.test_history_failure_rolls_back_status_and_serology_panel`.
- **Actual result/status:** see [execution record](execution.md) and CSV.

### TC-QNT-01-AK-08 — Bulk status updates cannot bypass history

- **Traceability:** TC-QNT-01; #14; BBMS-F-029.
- **Priority:** High. **Method:** automated regression with the manual/service procedure below.
- **Preconditions/data:** Existing unit with structured status history.
- **Steps:** Attempt queryset update and bulk_update of status.
- **Expected:** Unsupported bulk status changes are rejected rather than silently losing history.
- **Runnable test:** `inventory.test_status_integrity.StatusHistoryIntegrityTests.test_queryset_status_updates_and_bulk_updates_cannot_bypass_history`.
- **Actual result/status:** see [execution record](execution.md) and CSV.

### TC-QNT-01-AK-09 — Append-only status history

- **Traceability:** TC-QNT-01; #14; BBMS-F-029.
- **Priority:** High. **Method:** automated regression with the manual/service procedure below.
- **Preconditions/data:** Existing StatusChange record.
- **Steps:** Try editing/deleting history through supported model/queryset entry points.
- **Expected:** Mutation attempts are rejected and retained history is unchanged.
- **Runnable test:** `inventory.test_status_integrity.StatusHistoryIntegrityTests.test_status_history_is_append_only`.
- **Actual result/status:** see [execution record](execution.md) and CSV.

### TC-REQ-01-AK-01 — Unique pending requisitions

- **Traceability:** TC-REQ-01; #30; BBMS-F-043; BBMS-F-044.
- **Priority:** High. **Method:** automated regression with the manual/service procedure below.
- **Preconditions/data:** Active approved hospital; valid group/component, positive quantity, required-by date.
- **Steps:** Submit two requisitions and inspect their initial events.
- **Expected:** Unique request IDs, Pending status, correct owner/remaining quantity and submission actor/server time are persisted.
- **Runnable test:** `requisitions.tests.test_services.SubmissionTests.test_unique_pending_requests_and_submission_event`.
- **Actual result/status:** see [execution record](execution.md) and CSV.

### TC-REQ-01-AK-02 — Unapproved or inactive hospital submission

- **Traceability:** TC-REQ-01; #30; BBMS-F-042; BBMS-SR-003.
- **Priority:** High. **Method:** automated regression with the manual/service procedure below.
- **Preconditions/data:** Hospital account independently set unapproved or inactive.
- **Steps:** Attempt browser requisition submission in each state.
- **Expected:** Submission is denied without creating a requisition.
- **Runnable test:** `requisitions.tests.test_views.RequisitionViewTests.test_unapproved_or_inactive_hospital_cannot_submit`.
- **Actual result/status:** see [execution record](execution.md) and CSV.

### TC-REQ-01-AK-03 — Request input validation and atomic audit

- **Traceability:** TC-REQ-01; #30; BBMS-F-043; BBMS-SR-005.
- **Priority:** High. **Method:** automated regression with the manual/service procedure below.
- **Preconditions/data:** Approved hospital; quantity 0/-1/true/1.5, invalid group/component/STAT type or past required-by date.
- **Steps:** Submit each variant; then simulate submission-event failure for valid data.
- **Expected:** Invalid input persists no request; event failure also rolls back the request.
- **Runnable test:** `requisitions.tests.test_services.SubmissionTests.test_validation_and_atomic_submission_audit`.
- **Actual result/status:** see [execution record](execution.md) and CSV.

### TC-REQ-02-AK-01 — Staff approve/reject decisions

- **Traceability:** TC-REQ-02; #30; BBMS-F-045; BBMS-F-046.
- **Priority:** High. **Method:** automated regression with the manual/service procedure below.
- **Preconditions/data:** Pending requests; authorized staff and a rejection reason.
- **Steps:** Approve one request, reject another, inspect events.
- **Expected:** Decision status, responsible actor and rejection reason are recorded.
- **Runnable test:** `requisitions.tests.test_services.ReviewAndPriorityTests.test_approval_and_rejection_are_audited_with_actor_and_reason`.
- **Actual result/status:** see [execution record](execution.md) and CSV.

### TC-REQ-02-AK-02 — Hospital ownership isolation

- **Traceability:** TC-REQ-02; #30; BBMS-F-046; BBMS-SR-003.
- **Priority:** High. **Method:** automated regression with the manual/service procedure below.
- **Preconditions/data:** Two hospitals, one request belonging to the first.
- **Steps:** As the second hospital, attempt detail access and review.
- **Expected:** Foreign detail is hidden and unauthorized review cannot mutate the request.
- **Runnable test:** `requisitions.tests.test_views.RequisitionViewTests.test_hospital_cannot_see_another_hospital_request_or_review_it`.
- **Actual result/status:** see [execution record](execution.md) and CSV.

### TC-REQ-02-AK-03 — Stale review cannot overwrite priority change

- **Traceability:** TC-REQ-02; #30; BBMS-F-045.
- **Priority:** High. **Method:** automated regression with the manual/service procedure below.
- **Preconditions/data:** Pending request version 0; owner changes its priority.
- **Steps:** Review using version 0, then review using the current version.
- **Expected:** Stale review conflicts; current-version approval succeeds.
- **Runnable test:** `requisitions.tests.test_services.ReviewAndPriorityTests.test_stale_review_cannot_overwrite_priority_change`.
- **Actual result/status:** see [execution record](execution.md) and CSV.

### TC-REQ-01-AK-04 — Malformed request JSON

- **Traceability:** TC-REQ-01; #30; BBMS-F-043; BBMS-SR-005.
- **Priority:** High. **Method:** automated regression with the manual/service procedure below.
- **Preconditions/data:** Authenticated hospital; malformed JSON, wrong types, invalid fields/dates.
- **Steps:** POST invalid bodies to /api/requests/.
- **Expected:** Invalid requests receive 400 without persisting invalid data.
- **Runnable test:** `requisitions.tests.test_api.RequisitionAPITests.test_invalid_json_types_fields_and_dates_are_400`.
- **Actual result/status:** see [execution record](execution.md) and CSV.

### TC-REQ-03-AK-01 — STAT ordering and alert counts

- **Traceability:** TC-REQ-03; #30; BBMS-F-047; BBMS-F-048.
- **Priority:** High. **Method:** automated regression with the manual/service procedure below.
- **Preconditions/data:** One ordinary and two STAT pending requests.
- **Steps:** Read the staff queue and pending summary; approve one STAT request and read again.
- **Expected:** STAT requests precede ordinary requests in deterministic order; pending alert count decreases after review.
- **Runnable test:** `requisitions.tests.test_services.ReviewAndPriorityTests.test_stat_queue_and_alerts_follow_submission_and_review`.
- **Actual result/status:** see [execution record](execution.md) and CSV.

### TC-REQ-03-AK-02 — Live STAT alert response

- **Traceability:** TC-REQ-03; #30; BBMS-F-048.
- **Priority:** High. **Method:** automated regression with the manual/service procedure below.
- **Preconditions/data:** Staff queue open; another client submits a STAT request.
- **Steps:** Read the alert endpoint without reloading the full page.
- **Expected:** The response includes the new pending STAT request. Endpoint correctness is automated; visual refresh timing requires the manual check below.
- **Runnable test:** `requisitions.tests.test_views.RequisitionViewTests.test_live_alerts_include_new_stat_without_reloading_the_page`.
- **Actual result/status:** see [execution record](execution.md) and CSV.

### TC-REQ-03-AK-03 — Passive polling cannot keep idle login alive

- **Traceability:** TC-REQ-03; #30; BBMS-SR-006.
- **Priority:** High. **Method:** automated regression with the manual/service procedure below.
- **Preconditions/data:** Authenticated staff session; simulated 29-minute and 31-minute inactivity.
- **Steps:** Poll alerts at both times and compare stored expiry/cookies.
- **Expected:** The first poll does not renew expiry; after inactivity limit the poll receives 401 and clears the expired cookie.
- **Runnable test:** `requisitions.tests.test_polling_sessions.PassivePollingSessionTests.test_poll_cannot_extend_idle_session_and_expired_cookie_is_cleared`.
- **Actual result/status:** see [execution record](execution.md) and CSV.

### TC-DEL-01-AK-01 — Receipt identity, custody and counts

- **Traceability:** TC-DEL-01; #32; BBMS-F-056; BBMS-F-057.
- **Priority:** High. **Method:** automated regression with the manual/service procedure below.
- **Preconditions/data:** Owning approved hospital; two dispatched bags on a fulfilled request.
- **Steps:** Confirm one bag, inspect receipt/status/history/counts, then confirm the other.
- **Expected:** Selected bag becomes Delivered with authenticated receiver/server time; other bag stays Dispatched until confirmed. Dispatch fulfilment and available counts do not change.
- **Runnable test:** `requisitions.tests.test_delivery.DeliveryTests.test_receipt_keeps_fulfilment_and_available_counts_and_records_identity`.
- **Actual result/status:** see [execution record](execution.md) and CSV.

### TC-DEL-01-AK-02 — Receipt does not complete an under-supplied request

- **Traceability:** TC-DEL-01; #32; BBMS-F-045; BBMS-F-057.
- **Priority:** High. **Method:** automated regression with the manual/service procedure below.
- **Preconditions/data:** Request for two units with only one dispatched.
- **Steps:** Confirm receipt of the dispatched bag.
- **Expected:** Request remains Partially Fulfilled with one dispatched and one outstanding.
- **Runnable test:** `requisitions.tests.test_delivery.DeliveryTests.test_partial_dispatch_receipt_does_not_fulfil_remaining_quantity`.
- **Actual result/status:** see [execution record](execution.md) and CSV.

### TC-DEL-01-AK-03 — Duplicate/stale/mixed receipt batches

- **Traceability:** TC-DEL-01; #32; BBMS-F-056; BBMS-F-057.
- **Priority:** High. **Method:** automated regression with the manual/service procedure below.
- **Preconditions/data:** Two dispatched bags; first already confirmed; retain an old request version.
- **Steps:** Try repeat receipt, mixed confirmed/unconfirmed batch and stale-version receipt.
- **Expected:** Each conflicts atomically; second bag stays Dispatched and no extra receipt/version change occurs.
- **Runnable test:** `requisitions.tests.test_delivery.DeliveryTests.test_duplicate_stale_and_mixed_batches_are_atomic`.
- **Actual result/status:** see [execution record](execution.md) and CSV.

### TC-DEL-01-AK-04 — Only active approved owner can confirm

- **Traceability:** TC-DEL-01; #32; BBMS-F-056; BBMS-SR-003.
- **Priority:** High. **Method:** automated regression with the manual/service procedure below.
- **Preconditions/data:** Dispatched bag; foreign hospital, staff, admin, donor and unapproved owner.
- **Steps:** Attempt receipt as each disallowed actor.
- **Expected:** All are denied and no confirmation is stored.
- **Runnable test:** `requisitions.tests.test_delivery.DeliveryTests.test_only_active_approved_owner_can_confirm`.
- **Actual result/status:** see [execution record](execution.md) and CSV.

### TC-DEL-01-AK-05 — Unknown/foreign/duplicate/non-dispatched bags

- **Traceability:** TC-DEL-01; #32; BBMS-F-056; BBMS-SR-005.
- **Priority:** High. **Method:** automated regression with the manual/service procedure below.
- **Preconditions/data:** Own and foreign requests with bags; empty, wrong-type, duplicate and unknown Bag ID variants.
- **Steps:** Submit each invalid batch; also try a batch containing a now-discarded bag.
- **Expected:** Invalid batches fail without partial delivery or any receipt records.
- **Runnable test:** `requisitions.tests.test_delivery.DeliveryTests.test_rejects_foreign_unknown_duplicate_and_non_dispatched_bags`.
- **Actual result/status:** see [execution record](execution.md) and CSV.

### TC-DEL-01-AK-06 — Receipt audit failure rollback

- **Traceability:** TC-DEL-01; #32; BBMS-F-056; BBMS-F-057.
- **Priority:** High. **Method:** automated regression with the manual/service procedure below.
- **Preconditions/data:** Dispatched bag; inject requisition event failure.
- **Steps:** Attempt receipt and reload unit, request version, receipts and status history.
- **Expected:** Bag remains Dispatched, version is unchanged, and no receipt/Delivered history persists.
- **Runnable test:** `requisitions.tests.test_delivery.DeliveryTests.test_failure_in_audit_rolls_back_receipt_status_and_version`.
- **Actual result/status:** see [execution record](execution.md) and CSV.

### TC-DEL-01-AK-07 — Tracking and browser receipt

- **Traceability:** TC-DEL-01; #32; BBMS-F-046; BBMS-F-056.
- **Priority:** High. **Method:** automated regression with the manual/service procedure below.
- **Preconditions/data:** Owning hospital and dispatched manifest.
- **Steps:** Open request detail, confirm through HTML, inspect returned tracking JSON and staff view.
- **Expected:** Bag IDs/manifest appear; receipt renders Delivered and receiver; staff can inspect but cannot use the hospital receipt control.
- **Runnable test:** `requisitions.tests.test_delivery.DeliveryWebTests.test_tracking_page_api_and_html_confirmation`.
- **Actual result/status:** see [execution record](execution.md) and CSV.

### TC-DEL-01-AK-08 — Canonical delivery endpoint and replay

- **Traceability:** TC-DEL-01; #32; BBMS-F-056; BBMS-SR-005.
- **Priority:** High. **Method:** automated regression with the manual/service procedure below.
- **Preconditions/data:** Owning hospital; persisted fulfilment ID and current request version.
- **Steps:** POST to /api/deliveries/{fulfilment_id}/confirm/ twice with the same version.
- **Expected:** First receives 200, replay receives 409, and exactly one receipt exists.
- **Runnable test:** `requisitions.tests.test_delivery.DeliveryWebTests.test_canonical_delivery_api_and_repeated_submission`.
- **Actual result/status:** see [execution record](execution.md) and CSV.

### TC-REQ-02-AK-04 — Integrated partial/full fulfilment reconciliation

- **Traceability:** TC-REQ-02; #49; BBMS-F-045; BBMS-F-052–F-059.
- **Priority:** High. **Method:** automated regression with the manual/service procedure below.
- **Preconditions/data:** Real domain services; approved hospital; two safe bags plus quarantined/expired comparisons.
- **Steps:** Request and approve two units. Cross-match, allocate, dispatch and receive one bag at a time; inspect reports/counts/audit.
- **Expected:** Unsafe stock is excluded; partial then full dispatch state and two Delivered units reconcile with manifests, available count and a valid audit chain.
- **Runnable test:** `core.test_sprint2_integration.Sprint2IntegrationTests.test_partial_then_full_dispatch_receipt_reports_and_audit_reconcile`.
- **Actual result/status:** see [execution record](execution.md) and CSV.

### TC-NF-02-AK-01 — Real unhandled error and safe logging

- **Traceability:** TC-NF-02; #49; BBMS-NF-006.
- **Priority:** High. **Method:** automated regression with the manual/service procedure below.
- **Preconditions/data:** Controlled test-only URL configuration and captured django.request log.
- **Steps:** Trigger an unhandled exception through the client and inspect response/log record.
- **Expected:** Safe 500 response and timestamped exception information/stack trace are present; no fault route is added to deployed URLs.
- **Runnable test:** `core.test_nfr_reliability.ErrorLoggingAcceptanceTests.test_unhandled_error_records_timestamp_stack_trace_and_safe_response`.
- **Actual result/status:** see [execution record](execution.md) and CSV.

## Additional mandatory boundaries in the selected suites

The full modules are executed, including tests not given individual catalogue rows:
exact 90-day boundary, configurable 120-day interval and local-date handling;
empty histories and pagination; JSON types/content types/CSRF; safe no-op updates;
status history migration and actor retention; immutable receipts; direct unit-save
bypass prevention; request-method guards; and component-policy parity after INT-001.
See [test-modules.txt](test-modules.txt) for the complete scoped run. The catalogue
is a requirement-focused set of scenarios, not a one-row-per-assertion inventory.

## Manual and NFR follow-up cases (not inferred from automated passes)

These retain Abhinav's #49 coordination responsibility. Other owners provide
their feature evidence. Prior results are historical; none is a new 4 November run.

| ID / STP parent | Preconditions and procedure | Expected result | Current disposition |
| --- | --- | --- | --- |
| AK-MAN-01 / TC-REQ-03 | Staff queue in one browser, approved hospital in another; submit STAT and observe without reloading; record submission and appearance times. | Persistent visible alert refreshes on the configured 5-second polling cycle; reviewed requests leave pending summary. | Not run in this PR; endpoint/session regressions are separate. |
| AK-NF-01 / TC-NF-01 | Isolated representative server/data; run `demo/check_nfr.py` with 50 distinct sessions and retain per-request timings, configuration and response statuses. | Search ≤2s at up to 50 users, booking ≤3s, protected 50-session workload ≤2s. | Not rerun. Previous search max 6.669s FAILED; booking/concurrency passed locally. PERF-001 remains open in the acceptance record. |
| AK-NF-02 / TC-NF-02 | Commit synthetic domain records; save digest, reopen through a fresh process with `demo/verify_persistence.py`; compare digest. Separately monitor an agreed operating-hours interval. | Persisted records match; scheduled uptime ≥99%. | Reopen previously passed locally; uptime still Blocked without an observation window. Error-logging case is rerun above. |
| AK-NF-03 / TC-NF-03 | Independent first-time participant attempts registration; time it. Audit primary workflows by keyboard and measure text/control contrast. | Unassisted registration <5 minutes; keyboard operation and WCAG AA contrast; clear field errors. | Participant/timing/full accessibility checks Not run; form-validation automation alone is insufficient. |
| AK-NF-04 / TC-NF-04 | Review module boundaries; run all tests with statement coverage and a separate `coverage run --branch manage.py test`; retain reports/config/commit. | ≥60% business-logic statement coverage per SRS; report measured branch coverage separately. | No new whole-project coverage run in this owner-only test-case PR; team code/branch reports still required. Previous statement report is not branch evidence. |
| AK-NF-05 / TC-NF-05 | Record versions and run primary donor/hospital/staff flows on the latest two Chrome, Firefox and Edge versions plus supported runtime/OS matrix. | All required combinations execute correctly. | Not run; Django test client and prior Brave capture do not establish this matrix. |
| AK-NF-06 / TC-NF-06 | On an isolated multi-user RDBMS migrate schema/data and run competing allocation/receipt attempts; add a location as registry data and exercise filters. | Migration preserves data, competing writes do not double-count, and location addition needs no module rewrite. | Multi-user migration/concurrency Blocked; prior location architecture review is only partial evidence. |

## Deliverable handoff

The course requests updated test cases and four reports in `docs`: unit test,
system validation, code coverage and branch coverage. This contribution supplies
Abhinav's updated cases and an owner-scoped automated execution record, suitable
for the team to consolidate. It does not declare the four whole-project reports
complete or claim all STP cases passed. Keep other owners' cases and report results
when consolidating; reconcile any ownership/status differences against issue
assignments and actual evidence, rather than copying blanket Pass labels.

References: [original STP](../../../Deliverable%201/BBMS_Software_Test_Plan-1.pdf),
[requirements matrix](../../sprint2/requirements-traceability.csv),
[prior acceptance limitations](../../sprint2/acceptance.md).
