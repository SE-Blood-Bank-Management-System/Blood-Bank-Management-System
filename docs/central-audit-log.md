# Central Read-Only Tamper-Evident Audit Log

**Document ID**: BBMS-DOC-047<br>
**SRS Requirements**: BBMS-F-058, BBMS-F-059, BBMS-SR-008<br>
**Test Plan Cases**: TC-AUD-01, TC-SEC-08<br>
**Related Issue**: #47 (Consolidates Week 2 Sprint 2 baseline)

---

## 1. Executive Summary

Issue #47 establishes a centralized, append-only, tamper-evident audit service and an administrator viewer for the Blood Bank Management System (BBMS). It consolidates system-wide domain events and security operations into a unified cryptographic hash chain, guaranteeing auditability, non-repudiation, and immutability.

### Core Capabilities Delivered:
1. **Shared Append-Oriented Audit Service (BBMS-F-058, TC-AUD-01)**:
   - Unified audit logging across donor and hospital registrations, user creation, role changes, hospital approvals/revocations, user deactivations/reactivations, domain deletions, blood unit collections, quarantine and serology status changes, requisition submissions and fulfillments, authentication successes/failures, lockouts, and IP rate limiting.
   - Authoritative capture of actor/system identity (`actor`, `actor_label`), action code, server timestamp (`timezone.now()`), client IP address, target entity type and identifier, and sanitized event metadata.
2. **Domain Reference Retention & Sensitive Data Scrubbing (BBMS-SR-008, TC-SEC-08)**:
   - Historical references (`target_type`, `target_id`, `actor_label`) are retained permanently after domain entities (users, blood units, requisitions) are deleted.
   - Deleting an actor account sets foreign key `actor = NULL` (`on_delete=models.SET_NULL`) while preserving the immutable username snapshot `actor_label`.
   - Passwords, reset tokens, API keys, session tokens, CSRF tokens, and clinical details (questionnaires, symptoms, diagnoses, medical history) are recursively scrubbed before storage.
3. **Cryptographic Tamper Evidence & Hash Chaining (BBMS-SR-008, BBMS-F-058)**:
   - Every audit record seals its payload and the preceding record's hash using SHA-256 (`prev_hash`, `record_hash`).
   - Genesis record anchors the chain with a fixed 64-character zero string (`'0' * 64`).
   - `python manage.py verify_audit_integrity` command traverses the log sequentially and verifies both cryptographic content digests and chain continuity.
4. **Admin-Only Paginated Read-Only Viewer UI & API (BBMS-F-059, TC-AUD-01)**:
   - Web interface at `/audit-log/` (and `/admin/audit-log/`) with real-time cryptographic integrity status badge, actor filter, action filter, severity filter, date range filter, keyword search, and pagination (default 25 records per page).
   - REST API at `GET /api/audit-logs/` (and content negotiation via `Accept: application/json`).
   - Strict read-only controls: all mutation attempts (POST, PUT, PATCH, DELETE) return HTTP 405 Method Not Allowed.
   - Server-side RBAC: unauthenticated requests redirect to login or return 401; non-admin roles (DONOR, HOSPITAL, STAFF) receive HTTP 403 Forbidden.
5. **Multi-Layer Immutability Controls**:
   - Model-level `save()` and `delete()` reject modifications with `PermissionDenied`.
   - `SecurityAuditEventQuerySet` overrides `.update()`, `.delete()`, `.bulk_update()`, and `.bulk_create(update_conflicts=True)` to block bulk mutation paths.
   - Django admin panel `SecurityAuditEventAdmin` disables `add`, `change`, `delete`, and removes all bulk actions (`actions = None`).

---

## 2. Architecture & Cryptographic Hash Chaining

### Chain Topology

Each audit record $R_i$ forms a verifiable block chained to $R_{i-1}$:

```
+------------------------------------+       +------------------------------------+
| Audit Record 1 (Genesis)           |       | Audit Record 2                     |
| id: 1                              |       | id: 2                              |
| prev_hash: '0' * 64                | ----> | prev_hash: Hash(R1)                |
| timestamp: 2026-10-30T12:00:00Z    |       | timestamp: 2026-10-30T12:05:00Z    |
| action: 'donor_registered'         |       | action: 'unit_created'             |
| actor: 'jane.doe'                  |       | actor: 'staff_mary'                |
| record_hash: Hash(R1)              |       | record_hash: Hash(R2)              |
+------------------------------------+       +------------------------------------+
                                                                |
                                                                v
                                             +------------------------------------+
                                             | Audit Record 3                     |
                                             | id: 3                              |
                                             | prev_hash: Hash(R2)                |
                                             | timestamp: 2026-10-30T12:10:00Z    |
                                             | action: 'unit_status_changed'      |
                                             | actor: 'staff_mary'                |
                                             | record_hash: Hash(R3)              |
                                             +------------------------------------+
```

### Digest Computation

The record hash $H(R)$ is computed as the SHA-256 digest of canonical pipe-separated attributes:

$$\text{Payload} = \text{prev\_hash} \parallel \text{timestamp} \parallel \text{action} \parallel \text{severity} \parallel \text{actor\_label} \parallel \text{ip\_address} \parallel \text{target\_type} \parallel \text{target\_id} \parallel \text{details}$$

Where:
- `timestamp` is formatted in standard ISO-8601 representation (`YYYY-MM-DDTHH:MM:SS.ffffff+HH:MM`).
- `details` is serialized as deterministic JSON with keys sorted lexicographically and compact separators (`separators=(',', ':')`).
- `prev_hash` is the exact 64-character hexadecimal `record_hash` of the preceding record (or 64 zeroes for genesis).

---

## 3. Trust Assumptions & Threat Model

In compliance with Acceptance Criterion 4, the trust model and security boundaries are explicitly documented:

```
+-----------------------------------------------------------------------------------------+
| Threat Boundary & Trust Assumption Matrix                                               |
+-------------------------------------+-----------------------+---------------------------+
| Threat Vector                       | Protection Mechanism  | Trust Assumption          |
+-------------------------------------+-----------------------+---------------------------+
| Standard Web User / Attacker        | RBAC guards           | Server-side auth & 403    |
| Tampering via Application UI        | Read-only endpoints   | HTTP 405 on mutations     |
| Tampering via Django Admin Panel    | ModelAdmin overrides  | Add/Change/Delete denied  |
| Modification via Django ORM/Shell   | Custom QuerySet/Model | save/delete/update denied |
| Database Record Modification (SQL)  | SHA-256 Hash Chain    | verify_audit_integrity   |
| Database Record Deletion / Splice   | prev_hash Chain Link  | verify_audit_integrity   |
| Malicious DBA Rewriting Full DB     | Boundary Limitation   | OUT OF SCOPE (See below)  |
+-------------------------------------+-----------------------+---------------------------+
```

### Documented Trust Assumptions:
1. **Application-Level Immutability**: Application-level controls (ORM query restrictions, admin UI permissions, absence of edit/delete routes) prevent regular users, staff, and web-authenticated administrators from editing or deleting audit log records through web interfaces, Django admin, or standard application code.
2. **Cryptographic Tamper Evidence**: Any direct unauthorized modification or deletion of past records (e.g., via SQLite/raw SQL query) breaks either the record digest $H(R)$ or the chain linkage $R_{i}.\text{prev\_hash} = R_{i-1}.\text{record\_hash}$. This breakage is immediately detected by `python manage.py verify_audit_integrity`.
3. **Database Administrator (DBA) / Root Boundary**: Application-level read-only controls and software hash chaining **do not protect against an adversary with direct raw SQL, file-system, or operating system root access rewriting the entire database** and recomputing the entire hash chain from scratch. Complete protection against raw storage rewriting requires external trust anchors, such as streaming audit logs to external append-only log sinks (e.g., WORM storage, AWS CloudWatch, remote syslog) or signing periodic root hashes with a Hardware Security Module (HSM).

---

## 4. Supported Event Types & Domain Coverage

The shared audit service (`core.audit.record_audit_event`) captures all key lifecycle operations:

| Domain Area | Action Identifier | Triggering Event | Target Type | Captured Details |
| :--- | :--- | :--- | :--- | :--- |
| **Authentication** | `login_success` | Valid user credentials | `account` | Role, username |
| **Authentication** | `login_failed` | Invalid password / unknown ID | `account` | Consecutive failure count |
| **Brute-Force** | `account_locked` | 5 consecutive failures | `account` | Lockout duration (900s) |
| **Brute-Force** | `login_attempt_account_locked` | Attempt during lockout | `account` | Remaining lockout seconds |
| **Admin Action** | `lockout_cleared` | Admin clears lockout | `account` | Identifier |
| **Recovery** | `password_reset_request` | Reset email requested | `user` | Account email |
| **Recovery** | `password_reset_success` | Password changed via token | `user` | Timestamp |
| **Network Security**| `ip_rate_limited` | $>10$ req/min from source IP | `system` | Client IP, request path |
| **Donor Management**| `donor_registered` | Public donor registration | `user` | Username, role, email |
| **Hospital Management**| `hospital_registered` | Hospital registration | `user` | Hospital name, license |
| **User Administration**| `user_created` | Admin creates user | `user` | Role, username |
| **User Administration**| `role_changed` | Admin modifies user role | `user` | `old_role`, `new_role` |
| **User Administration**| `hospital_approved` | Admin approves hospital | `user` | Approval status |
| **User Administration**| `hospital_approval_revoked` | Admin revokes approval | `user` | Approval status |
| **User Administration**| `user_deactivated` | Admin deactivates account | `user` | Deactivation flag |
| **User Administration**| `user_reactivated` | Admin reactivates account | `user` | Activation flag |
| **User Administration**| `user_deleted` | User account deleted | `user` | Username snapshot |
| **Blood Inventory** | `unit_created` | Blood collection recorded | `blood_unit` | Bag ID, blood group, component |
| **Blood Inventory** | `unit_status_changed` | Quarantine/serology update | `blood_unit` | `previous_status`, `new_status` |
| **Blood Inventory** | `unit_deleted` | Blood unit deleted | `blood_unit` | Bag ID, component, status |
| **Requisitions** | `requisition_created` | Hospital submits request | `requisition` | Requisition ID, blood group |
| **Requisitions** | `requisition_status_changed`| Approved, rejected, dispatched| `requisition` | `previous_status`, `new_status` |
| **Requisitions** | `requisition_deleted` | Requisition deleted | `requisition` | Requisition ID, status |

---

## 5. Admin Viewer & API Endpoints

### 1. Web Viewer (`/audit-log/`)
- **Route**: `GET /audit-log/` (and `/admin/audit-log/`)
- **Access Control**: `@role_required('ADMIN')`
- **Features**:
  - Live cryptographic integrity banner (indicates whether chain is valid or tampered).
  - Multi-parameter filtering:
    - Actor filter: text match on `actor_label` or `actor__username`.
    - Action filter: dropdown of registered event actions.
    - Severity filter: `INFO`, `WARNING`, `ERROR`, `CRITICAL`.
    - Date range: `date_from` and `date_to` datepickers (`YYYY-MM-DD`).
    - Keyword search: full-text search across actor, action, target ID, and client IP.
  - Pagination: 25 items per page with persistent query parameters across page transitions.
  - Truncated SHA-256 hashes with full tooltips showing `prev_hash` and `record_hash`.

### 2. REST API (`/api/audit-logs/`)
- **Route**: `GET /api/audit-logs/` (or `Accept: application/json` on `/audit-log/`)
- **Access Control**: Returns HTTP 401 for anonymous, HTTP 403 for non-admin roles (`DONOR`, `HOSPITAL`, `STAFF`).
- **Response Format**:
  ```json
  {
    "count": 142,
    "num_pages": 6,
    "current_page": 1,
    "has_next": true,
    "has_previous": false,
    "integrity_valid": true,
    "total_verified": 142,
    "results": [
      {
        "id": 142,
        "timestamp": "2026-10-30T12:45:00.123456+00:00",
        "action": "unit_status_changed",
        "severity": "INFO",
        "actor": "staff_mary",
        "actor_id": 4,
        "ip_address": "127.0.0.1",
        "user_agent": "Mozilla/5.0 ...",
        "target_type": "blood_unit",
        "target_id": "BAG-20261030-9A1F2C",
        "details": {
          "blood_group": "O+",
          "component_type": "Whole Blood",
          "new_status": "Available",
          "previous_status": "Quarantined",
          "reason": "All required serology tests passed."
        },
        "prev_hash": "a4b5c6...89",
        "record_hash": "e7f8a1...34"
      }
    ]
  }
  ```

---

## 6. Verification CLI Command

To verify the integrity of the database audit records:

```bash
# Standard verification
python manage.py verify_audit_integrity

# Verbose output
python manage.py verify_audit_integrity --verbose

# Quiet mode (exit code only: 0 = valid, 1 = violation)
python manage.py verify_audit_integrity --quiet
```

### Verification Logic:
1. Loads all `SecurityAuditEvent` records ordered ascending by `id`.
2. Validates that record 0 has `prev_hash == ('0' * 64)`.
3. Validates that record $i$ ($i > 0$) has `prev_hash == record[i-1].record_hash`.
4. Recomputes $H(R)$ for each record and asserts that `record.record_hash == H(R)`.
5. If any mismatch is found, outputs the exact record ID and violation cause, exiting with error code 1.

---

## 7. Verification & Automated Test Evidence

Automated test cases for Issue #47 are implemented in `core/test_central_audit.py` (32 tests) and `accounts/test_security_audit.py` (6 tests):

| Test Suite | Test Count | Scope | Status |
| :--- | :--- | :--- | :--- |
| `core.test_central_audit.CentralAuditEventCoverageTests` | 9 | Donor/hosp registration, user creation, role changes, unit/req events, lockouts | **PASS** |
| `core.test_central_audit.AuditViewerPermissionsTests` | 5 | 401/403/405 guards, HTML/API admin access, ModelAdmin permissions | **PASS** |
| `core.test_central_audit.AuditRetentionAndScrubbingTests` | 3 | Actor deletion retention, target deletion, secret/medical scrubbing | **PASS** |
| `core.test_central_audit.AuditImmutabilityAndTamperEvidenceTests` | 6 | ORM/QuerySet update/delete denial, verify command, tamper detection | **PASS** |
| `core.test_central_audit.AuditRollbackAndConcurrencyTests` | 2 | Atomic transaction rollback, 4-thread concurrent hash chain append | **PASS** |
| `core.test_central_audit.AuditViewerFilteringTests` | 5 | Actor, action, severity, date range, pagination filters | **PASS** |
| `accounts.test_security_audit.SecurityAuditTests` | 6 | Immutability, credential scrubbing, 500 error server logging | **PASS** |

### Execution Commands:
```bash
# Feature test suite
python manage.py test core.test_central_audit accounts.test_security_audit

# Linting and syntax validation
flake8 .

# Integrity check command
python manage.py verify_audit_integrity
```
