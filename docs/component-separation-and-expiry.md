# Issue #35: Component Separation, Traceability, and Automatic Expiry

## Overview & Requirements

Implements Issue #35, SRS Section 4.10 (BBMS-F-031, BBMS-F-032), Section 4.12 (BBMS-F-037, BBMS-F-038, BBMS-F-039), and Test Plan specifications TC-CMP-01 and TC-EXP-01.

### 1. Component Separation & Traceability (BBMS-F-031, BBMS-F-032)
- **Staff Separation Interface**: Authorized staff/administrators can split safe Whole Blood into traceable components: Red Blood Cells (RBC), Platelets (Concentrate), and Fresh Frozen Plasma (FFP).
- **Unique Child Bag IDs**: Each derived component receives a globally unique Bag ID generated via `BloodUnit.generate_unique_bag_id()` (`BAG-<YYYYMMDD>-<HEX6>`).
- **Parent Unit Linkage**: Every child unit maintains a foreign key `parent_unit` pointing to the originating Whole Blood unit, establishing permanent bidirectional traceability.
- **Inheritance of Donor & Lab Blood Group**: Child units automatically inherit the parent's registered donor, laboratory-confirmed blood group, storage facility location, and collection date anchor.
- **Serology Inheritance**: All four mandatory infection clearance results (HIV, Hepatitis B, Hepatitis C, Syphilis) are copied from the parent to each child unit with audit notes.
- **Stock Double-Counting Prevention**: Upon separation, the parent Whole Blood unit transitions to `BloodUnitStatus.SEPARATED` with an audit trail, removing it from allocatable counts so parent and children are never counted together.
- **Safety Gate**: Non-Whole Blood units, units not in `Available` status, units with incomplete/failed serology, expired units, or units that have already been separated are strictly rejected from separation.

### 2. Shelf-Life Anchoring & Expiry Integrity (BBMS-F-037, TC-EXP-01)
- **Component Shelf Lives**:
  - Whole Blood / RBC: 42 days
  - Platelets: 5 days
  - Fresh Frozen Plasma (FFP): 365 days
- **Anchoring to Source Collection**: Child component expiry dates are strictly calculated from the originating unit's `collection_date`, never from the time of separation (`child.expiry_date = parent.collection_date + timedelta(days=shelf_life)`).
- **Overdue Stock Handling**: If an older Whole Blood unit (e.g. collected 10 days ago) is separated, short-shelf-life components (e.g. Platelets, shelf life 5 days) are marked `Expired` immediately upon derivation, guaranteeing that separation never rejuvenates expiring stock.

### 3. Automatic Expiry Service & Management Command (BBMS-F-038, BBMS-F-039)
- **Service (`process_expired_units`)**:
  - Scans active blood units whose `expiry_date <= as_of`.
  - Eligible statuses: `Available`, `Quarantined`, and `Allocated`.
  - Transitions eligible units to `BloodUnitStatus.EXPIRED` with system or staff audit logs.
  - Excludes final or retired states (`Expired`, `Discarded`, `Dispatched`, `Delivered`, `Separated`).
  - Supports `--dry-run` to preview eligible units without database writes.
  - Idempotent: repeated runs produce zero duplicate changes.
- **CLI Management Command**:
  ```bash
  python manage.py expire_units [--dry-run] [--as-of YYYY-MM-DDTHH:MM:SS]
  ```

---

## Architecture & Data Flow

```
[ Whole Blood Unit ] (Status: Available, Passed Serology)
        │
        ├── Centrifugation & Separation (separate_into_components)
        │
        ├──> Parent Unit Status -> [ Separated ] (Excluded from available counts)
        │
        ├──> Child 1: [ Red Blood Cells ] (parent_unit=Parent, Expiry = collection_date + 42d)
        ├──> Child 2: [ Platelets ]       (parent_unit=Parent, Expiry = collection_date + 5d)
        └──> Child 3: [ Plasma ]          (parent_unit=Parent, Expiry = collection_date + 365d)
```

---

## Views & REST API Endpoints

| Method | URL | Role | Description |
|---|---|---|---|
| `GET` | `/inventory/blood-units/<bag_id>/separate/` | Staff / Admin | Renders HTML staff component separation form. |
| `POST` | `/inventory/blood-units/<bag_id>/separate/` | Staff / Admin | Submits component separation form and derives child units. |
| `POST` | `/api/blood-units/<bag_id>/components/` | Staff / Admin | SAD Section 4.3 REST API for programmatic component separation. |
| `POST` | `/api/inventory/expire/` | Staff / Admin | Triggers automated expiry processing service. |

---

## Automated Verification

Automated test suite `inventory/test_component_separation_and_expiry.py` provides 17 test cases covering:
1. `TC-CMP-01`: Tri-pack separation, unique child IDs, parent reference, serology inheritance, parent exclusion from stock counts.
2. `TC-EXP-01`: Expiry calculation anchored to source collection date; immediate expiry for overdue platelets; automated expiry service and idempotency.
3. Safety validations: Rejection of non-Whole Blood, quarantined, discarded, expired, or repeated separations.
4. Transaction rollback: Integrity preservation under unexpected mid-separation errors.
5. RBAC security: Rejecting unauthorized Donor and Hospital accounts with 403 Forbidden.
