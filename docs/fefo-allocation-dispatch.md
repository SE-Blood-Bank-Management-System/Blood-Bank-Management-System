# FEFO Allocation, Dispatch Manifests and Requisition Fulfilment (Issue #37)

**Assignee:** Akshay Kumar (@Akshayarcot)  
**SRS References:** Section 4.11 (BBMS-F-035), Section 4.12 (BBMS-F-038, BBMS-F-039), Section 4.16 (BBMS-F-049 to BBMS-F-051), Section 4.17 (BBMS-F-052 to BBMS-F-055)  
**STP Test Cases:** TC-INV-01, TC-INV-02, TC-EXP-01, TC-MATCH-01, TC-DISP-01  
**SAD References:** Section 3.4 (Compatibility & Allocation; Dispatch & Delivery), Section 4.3 (REST API), Section 5.1 (SQLite Concurrency & Transaction Safeguards)  

---

## 1. Overview & Workflow

The **FEFO Allocation & Dispatch Manifest** module delivers an end-to-end, transactionally secure fulfilment workflow for hospital blood requisitions:

1. **FEFO Suggestion Engine (BBMS-F-038):**
   - Automatically identifies compatible, safe, unexpired `Available` stock for an approved requisition.
   - Sorts candidates strictly in First-Expiry-First-Out (FEFO) order (`expiry_date ASC`).
   - Employs deterministic tie-breaking on `collection_date ASC` and `bag_id ASC`.
   - Strictly excludes Quarantined, Discarded, Expired, and already-reserved units.

2. **ABO/Rh Compatibility & Staff Override (BBMS-F-049, BBMS-F-050, BBMS-F-051):**
   - Evaluates recipient-donor compatibility using the red blood cell transfusion matrix (`RBC_COMPATIBILITY_RULES`).
   - Automatically blocks allocation of incompatible blood units unless an authorized staff member supplies an explicit clinical override justification.
   - Persists the cross-match outcome (`Compatible` or `Overridden`), the acting staff user, timestamp, and clinical rationale on the `Allocation` model.

3. **Atomic Unit Reservation & Stock Auto-Decrement (BBMS-F-035, BBMS-F-052):**
   - Transitions blood unit status atomically from `Available` to `Allocated`.
   - Immediately decrements the available inventory count across all dashboards without double-counting.
   - Enforces database unique constraints (`unique_active_unit_reservation`) to prevent duplicate reservations, concurrent double-claims, and over-allocation beyond the requested quantity.

4. **Dispatch Manifest Execution & Recheck (BBMS-F-053, BBMS-F-054):**
   - Prior to dispatch execution, re-verifies unit safety (serology clearance, non-expired status, component match, and ownership by the requisition).
   - Atomically transitions units to `Dispatched` and generates a permanent `DispatchManifest` with unique tracking ID `MAN-<YYYYMMDD>-<HEX6>`, destination hospital, dispatching staff identity, and server timestamp.
   - Integrates with `record_dispatched_units()` to generate non-editable `RequisitionFulfilment` facts and `RequisitionEvent` audit logs.

5. **Cumulative Fulfilment Progress (BBMS-F-055):**
   - Updates requisition state to `Partially Fulfilled` or `Fulfilled` based on actual cumulative dispatched units.
   - Accurately tracks remaining needed quantity across single or multiple dispatches.

---

## 2. Domain Models & SQLite Transaction Safeguards

### `Allocation`
- Stores individual unit reservations against an approved `Requisition`.
- Fields: `allocation_id`, `requisition`, `blood_unit`, `cross_match_outcome` (`Compatible`, `Incompatible`, `Overridden`), `override_reason`, `allocated_by`, `allocated_at`, `status` (`Reserved`, `Dispatched`, `Cancelled`), `cancelled_at`, `cancelled_by`, `cancellation_reason`.
- Constraints:
  - `UniqueConstraint`: Only one active `Reserved` allocation per `blood_unit`.
  - `CheckConstraint`: Mandatory `override_reason` when `cross_match_outcome == 'Overridden'`.

### `DispatchManifest`
- Immutable chain-of-custody transfer record.
- Fields: `manifest_id` (unique `MAN-YYYYMMDD-HEX6`), `requisition`, `dispatched_by`, `dispatched_at`, `units` (ManyToMany), `notes`.
- Provides printable manifest views for blood transport couriers and hospital receiving staff.

### SQLite Concurrency Safeguards
SQLite does not provide row-level locks via `select_for_update()`. The system guarantees transactional integrity through:
- Outer `transaction.atomic()` boundaries.
- Database unique constraints preventing duplicate active reservations.
- Handling `OperationalError` ("database is locked") and `IntegrityError` by raising clean, retryable domain exceptions (`AllocationConflict`).

---

## 3. Web UI & REST API Endpoints

### HTML Routes
- **Allocation View:** `GET /inventory/requisitions/<pk>/allocate/` & `POST /inventory/requisitions/<pk>/allocate/`
- **Dispatch View:** `GET /inventory/requisitions/<pk>/dispatch/` & `POST /inventory/requisitions/<pk>/dispatch/`
- **Printable Manifest View:** `GET /inventory/manifests/<manifest_id>/`
- **Requisition Detail Integration:** `GET /requisitions/<pk>/` (shows allocated units, dispatch manifest links, and staff allocation buttons).

### REST API Endpoints
| Method | Route | Role | Purpose |
|---|---|---|---|
| `GET` | `/api/inventory/requisitions/<pk>/suggestions/` | Staff/Admin | Retrieve FEFO ordered matching units |
| `POST` | `/api/inventory/requisitions/<pk>/allocate/` | Staff/Admin | Atomically allocate units by Bag ID with optional override |
| `POST` | `/api/inventory/requisitions/<pk>/dispatch/` | Staff/Admin | Dispatch reserved units and generate manifest |
| `GET` | `/api/inventory/manifests/<manifest_id>/` | Staff/Hospital | Inspect formal dispatch manifest details |

---

## 4. Requirements Traceability Matrix

| Requirement | Description | Test Case | Automated Verification |
|---|---|---|---|
| **BBMS-F-035** | Auto-decrement available inventory count on allocation | `TC-INV-02` | `test_tc_inv_02_count_decrement_on_allocation_and_dispatch` |
| **BBMS-F-038** | FEFO ordering for suggested allocation | `TC-INV-01` | `test_tc_inv_01_fefo_suggestion_ordering` |
| **BBMS-F-039** | Exclude expired units from counts and allocation | `TC-EXP-01` | `test_tc_exp_01_expired_units_blocked_from_allocation` |
| **BBMS-F-049** | ABO/Rh compatibility evaluation | `TC-MATCH-01` | `test_tc_match_01_compatible_allocation_recorded` |
| **BBMS-F-050** | Block incompatible blood unless clinical override justified | `TC-MATCH-01` | `test_tc_match_01_incompatible_allocation_blocked_without_override` |
| **BBMS-F-051** | Record cross-match outcome against allocation | `TC-MATCH-01` | `test_tc_match_01_incompatible_allocation_permitted_with_override` |
| **BBMS-F-052** | Allocate specific blood units by Bag ID | `TC-DISP-01` | `test_tc_disp_01_partial_and_full_dispatch_fulfilment` |
| **BBMS-F-053** | Generate dispatch manifest record | `TC-DISP-01` | `test_tc_disp_01_partial_and_full_dispatch_fulfilment` |
| **BBMS-F-054** | Mark units Dispatched and avoid double-decrement | `TC-INV-02` | `test_tc_inv_02_count_decrement_on_allocation_and_dispatch` |
| **BBMS-F-055** | Update requisition to Partially Fulfilled / Fulfilled | `TC-DISP-01` | `test_tc_disp_01_partial_and_full_dispatch_fulfilment` |
