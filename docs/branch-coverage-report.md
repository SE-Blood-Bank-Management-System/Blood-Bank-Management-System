# BBMS Branch Coverage Report

**Document ID**: BBMS-REP-BR-001<br>
**Project**: Blood Bank Management System (BBMS) - Software Engineering Mini-Project<br>
**Version**: 1.0<br>
**Evaluation Window**: 2nd November 2026 – 6th November 2026<br>
**Authors**: Team T9
- **Uttam** (PES1UG24CS697) — *Authentication, Security & Audit Branching Logic*
- **Abhinav K** (PES1UG24CS701) — *Hospital Requisitions & STAT Queue Branching Logic*
- **Akshay Arcot** (PES1UG24CS705) — *FEFO Ordering, Dispatch & Reporting Branching Logic*
- **Navaneeth Tanuboddi** (PES1UG24CS709) — *Eligibility, Serology & Compatibility Branching Logic*

**Measurement Tool**: Coverage.py 7.17.1 with Branch Tracing (`coverage run --branch`)<br>
**Evaluation Target**: Comprehensive Branch Verification across Decision Points, State Machines & Security Guards

---

## 1. Executive Summary

Branch coverage evaluates whether every boolean decision outcome (both `True` and `False` branches) across conditionals, loops, exception clauses, and state machines is exercised during test execution.

### Branch Coverage Summary:
```
+-------------------------------------------------------------------------+
| Metric Category                     | Total Branches | Partial | Cover %|
+-------------------------------------------------------------------------+
| Application Business-Logic Code     |     1,314      |   264   | 79.0%  |
| Total Repository (Including Tests)  |     1,542      |   274   | 82.0%  |
+-------------------------------------------------------------------------+
```

Across **1,314 decision branches** in the application codebase, **79.0%** are fully executed in both directions by the test suite, demonstrating deep path coverage across security controls, medical safety logic, and inventory lifecycles.

---

## 2. Branch Coverage by Application

```
+------------------+-----------------+------------------+-----------------+
| Application      | Total Branches  | Partial Branches | Branch Cover %  |
+------------------+-----------------+------------------+-----------------+
| accounts         |       200       |        40        |      80.0%      |
| appointments     |       174       |        45        |      74.0%      |
| donors           |        82       |         9        |      89.0%      |
| inventory        |       552       |       118        |      79.0%      |
| requisitions     |       208       |        28        |      87.0%      |
| core             |       206       |        33        |      84.0%      |
+------------------+-----------------+------------------+-----------------+
| TOTAL APPS       |     1,314       |       264        |      79.0%      |
+------------------+-----------------+------------------+-----------------+
```

---

## 3. Analysis of Critical Decision Trees

### 3.1 Authentication, Security & RBAC Decision Trees
*Implemented in `accounts/security.py`, `accounts/middleware.py`, `accounts/rbac.py`*

1. **Brute-Force Account Lockout Counter (`SR-007`)**:
   - `consecutive_failed < 5`: Increments failure counter, remains unlocked $\rightarrow$ **Tested (True & False)**.
   - `consecutive_failed >= 5`: Sets `lockout_until = now + 15 min`, logs warning $\rightarrow$ **Tested (True & False)**.
   - `now < lockout_until`: Blocks authentication, calculates remaining lockout seconds $\rightarrow$ **Tested (True & False)**.
   - Successful login: Resets counter to 0, clears `lockout_until` $\rightarrow$ **Tested**.

2. **Sliding-Window IP Rate Limiting (`SR-007`)**:
   - `recent_requests_count <= 10`: Request proceeds through middleware $\rightarrow$ **Tested (True)**.
   - `recent_requests_count > 10`: Request terminated immediately with HTTP 429 and `Retry-After: 60` $\rightarrow$ **Tested (True)**.

3. **Trusted Proxy Boundary Evaluation (`SR-007`, `SR-008`)**:
   - Direct connection `REMOTE_ADDR in BBMS_TRUSTED_PROXIES`: Parses `HTTP_X_FORWARDED_FOR` $\rightarrow$ **Tested (True)**.
   - Direct connection `REMOTE_ADDR not in BBMS_TRUSTED_PROXIES`: Untrusted header ignored, authoritatively uses `REMOTE_ADDR` $\rightarrow$ **Tested (False)**.

4. **Time-Limited Password Reset Token (`BBMS-F-005`)**:
   - Token age $\le 900$s (15 min) and user password hash unchanged: Renders password change form $\rightarrow$ **Tested (True)**.
   - Token age $> 900$s or password already changed: Rejects with `validlink = False` $\rightarrow$ **Tested (False)**.

5. **Server-Side RBAC Enforcement (`BBMS-SR-003`)**:
   - User authenticated and `user.role == required_role`: View execution permitted $\rightarrow$ **Tested (True)**.
   - User authenticated but `user.role != required_role`: Denied with HTTP 403 Forbidden $\rightarrow$ **Tested (False)**.
   - User unauthenticated: Denied with HTTP 302 redirect / HTTP 401 $\rightarrow$ **Tested (False)**.

---

### 3.2 Inventory, Testing & Component Separation Decision Trees
*Implemented in `inventory/models.py`, `inventory/services.py`*

1. **Mandatory Serology Screening Panel (`BBMS-F-024`–`F-027`)**:
   - `all(tests == PASS)`: Status transitions from `Quarantined` $\rightarrow$ `Available`, calculates 42-day FEFO expiry $\rightarrow$ **Tested (True)**.
   - `any(tests == FAIL)`: Status transitions from `Quarantined` $\rightarrow$ `Discarded`, blocks all allocation $\rightarrow$ **Tested (False)**.
   - Incomplete panel: Unit remains strictly `Quarantined` $\rightarrow$ **Tested**.

2. **Component Separation Validity (`BBMS-F-031`, `BBMS-F-032`)**:
   - Unit `status == Quarantined` and `component_type == WHOLE_BLOOD`: Generates RBC, Platelets, and FFP units, marks parent `Separated` $\rightarrow$ **Tested (True)**.
   - Unit is not Whole Blood or already Discarded/Expired: Separation rejected with `ValidationError` $\rightarrow$ **Tested (False)**.

3. **Component Expiry Evaluation (`BBMS-F-037`–`F-039`)**:
   - `expiry_date < today` and status `Available`: Automatically transitions to `Expired` $\rightarrow$ **Tested (True)**.
   - `expiry_date >= today`: Remains `Available` for allocation $\rightarrow$ **Tested (False)**.

4. **First-Expiry-First-Out (FEFO) Allocation Ordering (`BBMS-F-038`)**:
   - Queries candidate units matching blood group and component, ordered by `expiry_date ASC` $\rightarrow$ **Tested**.

---

### 3.3 Hospital Requisitions, STAT Queue & Compatibility Decision Trees
*Implemented in `requisitions/services.py`, `requisitions/compatibility.py`*

1. **STAT Emergency Prioritization (`BBMS-F-047`, `BBMS-F-048`)**:
   - `is_stat == True`: Placed at top of staff review queue (`order_by('-is_stat', 'created_at')`), triggers 5-second polling alert $\rightarrow$ **Tested (True)**.
   - `is_stat == False`: Standard FIFO priority $\rightarrow$ **Tested (False)**.

2. **ABO/Rh Transfusion Cross-Matching (`BBMS-F-049`–`F-051`)**:
   - Unit blood group in `get_compatible_donor_groups(patient_group, component)`: Marked `CrossMatchOutcome.COMPATIBLE` $\rightarrow$ **Tested (True)**.
   - Unit incompatible and clinical justification provided by authorized staff: Marked `CrossMatchOutcome.OVERRIDDEN` $\rightarrow$ **Tested (True)**.
   - Unit incompatible and no override justification: Allocation blocked with `PermissionDenied` $\rightarrow$ **Tested (False)**.

3. **Requisition Fulfilment Completeness (`BBMS-F-054`)**:
   - `allocated_quantity == requested_quantity`: Transitions requisition to `Fulfilled` $\rightarrow$ **Tested (True)**.
   - `0 < allocated_quantity < requested_quantity`: Transitions requisition to `Partially Fulfilled` $\rightarrow$ **Tested (False)**.

4. **Hospital Delivery Confirmation (`BBMS-F-056`, `BBMS-F-057`)**:
   - Unit in `Dispatched` state and confirmed by owning hospital: Status becomes `Delivered`, captures timestamp and receiver $\rightarrow$ **Tested (True)**.
   - Unit not in `Dispatched` state or non-owning hospital: Rejection $\rightarrow$ **Tested (False)**.

---

### 3.4 Cryptographic Audit Trail & Immutability Decision Trees
*Implemented in `core/audit.py`, `core/models.py`*

1. **SHA-256 Hash Chaining Anchor (`BBMS-SR-008`)**:
   - First audit record (`id == 1`): Sets `prev_hash = '0' * 64` (Genesis Anchor) $\rightarrow$ **Tested (True)**.
   - Subsequent records (`id > 1`): Sets `prev_hash = preceding_record.record_hash` $\rightarrow$ **Tested (False)**.

2. **Tamper Detection Verification Loop (`BBMS-F-058`)**:
   - `computed_hash == stored_hash` and `prev_hash == prior_hash`: Check passes, continues verification $\rightarrow$ **Tested (True)**.
   - Any digest mismatch detected: Raises `CommandError` with exact tampered record ID $\rightarrow$ **Tested (False)**.

3. **Multi-Layer Mutation Prevention (`BBMS-F-059`)**:
   - Existing instance `self.pk is not None`: `.save()` and `.delete()` raise `PermissionDenied` $\rightarrow$ **Tested (True)**.
   - Bulk queryset `.update()` or `.delete()`: QuerySet methods raise `PermissionDenied` $\rightarrow$ **Tested (True)**.

---

## 4. Analysis of Partial Branches

Of the 264 partial branches (21% of application branches):
1. **Defensive Model Validation Branches**: Checks such as `if obj is not None:` where the ORM query guarantees a non-null instance under normal execution.
2. **Multi-Condition Safeguards**: Complex compound expressions such as `if user.is_authenticated and user.is_active and user.has_perm(...):` where unauthenticated requests short-circuit before evaluating later expressions.
3. **Emergency Logging Fallbacks**: Exception blocks in the audit logger that write to standard error if database logging fails.

---

## 5. Verification Command

To regenerate the branch coverage data:

```bash
.venv/bin/coverage report -m --branch --omit="*/tests*/*,*/tests.py,*/test_*.py,*/migrations/*"
```
