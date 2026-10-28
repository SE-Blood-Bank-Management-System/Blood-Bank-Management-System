# Issue #36: Compatibility Cross-Matching and Justified Staff Overrides

## Overview & Requirements

Implements Issue #36, SRS Section 4.16 (BBMS-F-049, BBMS-F-050, BBMS-F-051), SAD Section 3.4 / 4.3 (`POST /api/requests/{id}/cross-match`), and Test Plan specifications `TC-MATCH-01`, `TC-SEC-03`, and `TC-SEC-08`.

---

## 1. Transfusion Compatibility Policy Service (`requisitions/compatibility.py`)

### Component-Specific Compatibility Rules
 ट्रांसफ्यूजन मेडिसिन (Transfusion medicine) operates under component-specific immunological rules:
1. **Red Blood Cells (RBC) & Whole Blood (SRS BBMS-F-049)**:
   - Evaluated based on recipient antibodies reacting with donor erythrocyte surface antigens.
   - Reuses `core.constants.RBC_COMPATIBILITY_RULES`:
     - O- recipient: O- only (universal donor is O-).
     - O+ recipient: O-, O+.
     - A- recipient: O-, A-.
     - A+ recipient: O-, O+, A-, A+.
     - B- recipient: O-, B-.
     - B+ recipient: O-, O+, B-, B+.
     - AB- recipient: O-, A-, B-, AB-.
     - AB+ recipient: All 8 groups (universal recipient is AB+).
2. **Fresh Frozen Plasma (FFP)**:
   - Acellular plasma contains isohemagglutinins (anti-A and anti-B antibodies) rather than red cell antigens.
   - Plasma compatibility is the reverse of red cells:
     - Group AB plasma lacks anti-A and anti-B antibodies -> Universal Plasma Donor!
     - Group O plasma contains both anti-A and anti-B antibodies -> Transfused only to Group O.
     - Recipient O: Can receive plasma from all groups (O, A, B, AB).
     - Recipient A: Can receive plasma from A and AB.
     - Recipient B: Can receive plasma from B and AB.
     - Recipient AB: Can receive plasma from AB only.
     - Rh factor in acellular plasma is non-immunogenic for routine transfusion, permitting Rh+ or Rh- plasma across recipient Rh types when identical stock is depleted.
3. **Platelets**:
   - ABO identical is preferred; ABO-compatible (RBC-compatible) is clinically acceptable when identical units are depleted.

---

## 2. Incompatible Allocation Restriction & Staff Overrides (BBMS-F-050)

- **Mandatory Block**: Blood bank staff are strictly prohibited from cross-matching or allocating a biologically incompatible unit unless an explicitly authorized staff member provides an override justification.
- **Inviolable Safety Invariants**: An override **never** bypasses core safety checks:
  - Expired units (`expiry_date <= now`) are strictly rejected under all circumstances.
  - Units with incomplete or failed serology screening (quarantined or discarded) are strictly rejected.
  - Component mismatches (e.g. Platelets for an RBC requisition) are rejected.
  - Requisitions that are not `Approved` or `Partially Fulfilled` cannot be cross-matched.
  - Units already fulfilled or dispatched to another requisition are excluded.

---

## 3. Auditable Cross-Match Decisions (BBMS-F-051)

- Model `CrossMatchDecision(AppendOnlyModel)` records:
  - `requisition`: Associated blood requisition FK.
  - `blood_unit`: Candidate inventory unit FK.
  - `requested_blood_group`: Requisition blood group.
  - `donor_blood_group`: Unit laboratory-confirmed blood group.
  - `component_type`: Requisition component.
  - `outcome`: `Compatible`, `Incompatible`, or `Overridden`.
  - `is_compatible`: Boolean biological compatibility result.
  - `is_overridden`: Boolean flag indicating clinical override authorization.
  - `override_reason`: Mandatory text justification supplied by staff for overridden units.
  - `performed_by`: Responsible staff member FK and username snapshot.
  - `performed_at`: Timestamp.
- Every cross-match generates a permanent append-only `RequisitionEvent` with action `Cross-match recorded`.

---

## 4. REST API & Web UI

### REST API (SAD Section 4.3)
`POST /api/requests/{id}/cross-match/` (Role: Staff / Administrator)
- **Request Body**:
  ```json
  {
    "bagId": "BAG-20261028-A1B2C3",
    "overrideReason": "Emergency extreme shortage protocol authorized by Chief Medical Officer Dr. Evans."
  }
  ```
- **Response (`200 OK` or `201 Created` for overrides)**:
  ```json
  {
    "success": true,
    "decisionId": 42,
    "requestId": "REQ-7F89...",
    "bagId": "BAG-20261028-A1B2C3",
    "requestedBloodGroup": "A+",
    "donorBloodGroup": "B+",
    "component": "Red Blood Cells",
    "outcome": "Overridden",
    "isCompatible": false,
    "isOverridden": true,
    "overrideReason": "Emergency extreme shortage protocol...",
    "explanation": "ABO/Rh incompatible RBC match (B+ to A+)...",
    "performedBy": "staff_kevin",
    "performedAt": "2026-10-29T00:20:00Z"
  }
  ```

### Staff Web UI
- Requisition Detail (`/requisitions/<pk>/`):
  - Renders compatible blood groups for requested component.
  - Suggests available FEFO-compatible inventory units.
  - Provides interactive Cross-Match & Override form.
  - Displays persistent Cross-Matching Audit Trail table.

---

## 5. Automated Verification (TC-MATCH-01)

Automated test suite `requisitions/tests/test_cross_matching.py` provides 17 test cases verifying:
1. RBC compatibility matrix across all 8 ABO/Rh groups.
2. Plasma compatibility inverse antibody rules and clinical explanations.
3. Successful recording of `Compatible` cross-match without override.
4. Strict blocking of incompatible units without override justification.
5. Successful recording of `Overridden` cross-match with staff rationale.
6. Safety preservation: rejection of expired, unpassed serology, quarantined, and mismatched component units.
7. Role-based access control: blocking donor and hospital accounts with 403 Forbidden.
8. FEFO ordering of compatible suggested inventory.
