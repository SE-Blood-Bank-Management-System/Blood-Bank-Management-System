# Serology Testing, Quarantine Rules & Expiry Management

**SRS References:** Section 4.8 (BBMS-F-024 to BBMS-F-027), Section 4.9 (BBMS-F-028 to BBMS-F-030), Section 4.12 (BBMS-F-037)  
**STP Test Cases:** TC-SER-01, TC-SER-02, TC-QNT-01  
**GitHub Issue:** #12 (Serology testing and quarantine rules)

---

## 1. Overview & Requirements Traceability

The **Serology & Quarantine Engine** governs the clinical safety verification of collected blood units before they can be released for inventory allocation and transfusion:

| Requirement ID | Description | Enforcement Point | Verified By |
| :--- | :--- | :--- | :--- |
| **BBMS-F-024** | Every collected blood unit must undergo recorded serology testing for HIV, Hepatitis B, Hepatitis C, and Syphilis before becoming Available. | `BloodUnit.evaluate_serology_status()`, `BloodUnit.clean()` | TC-SER-01, TC-SER-02 |
| **BBMS-F-025** | Authorized blood bank staff may record a `Pass` or `Fail` result for each serology test. | `BloodUnit.record_serology_test()`, `SerologyPanelForm` | TC-SER-01, TC-SER-02 |
| **BBMS-F-026** | Unit status defaults to `Quarantined` upon collection. Status cannot become `Available` until all 4 required tests are recorded as `Pass`. | `BloodUnitStatus.QUARANTINED`, `BloodUnit.clean()`, `save()` | TC-SER-01, TC-SER-02 |
| **BBMS-F-027** | If any serology test fails (`Fail`), unit status immediately transitions to `Discarded`. Discarded units cannot be allocated or dispatched. | `BloodUnit.evaluate_serology_status()`, `BloodUnit.clean()` | TC-SER-01 |
| **BBMS-F-028** | Quarantined and Discarded units are excluded from available inventory counts and hospital searches. | `BloodUnitQuerySet.available()`, `inventory_dashboard` | TC-QNT-01, TC-SER-01 |
| **BBMS-F-029** | Log staff identity and timestamp whenever a blood unit's status transitions to or from `Quarantined`. | `BloodUnit.log_status_change()`, `BloodUnit.status_audit_log` | TC-QNT-01, TC-SER-01 |
| **BBMS-F-030** | Authorized staff can view all currently quarantined units and elapsed quarantine duration in days. | `BloodUnit.quarantine_duration_days`, `/inventory/quarantine/` | TC-QNT-01 |
| **BBMS-F-037** | Automatically calculate and set expiry date upon becoming `Available` based on component shelf life (42 days for Whole Blood/RBC, 5 days for Platelets). | `BloodUnit.calculate_default_expiry()`, `evaluate_serology_status()` | TC-SER-01, TC-EXP-01 |
| **BBMS-SR-003** | Server-side role-based access control restricts serology test recording strictly to `STAFF` and `ADMIN` users. | `@role_required(User.Role.STAFF, User.Role.ADMIN)` | RBAC Tests |

---

## 2. State Machine & Automated Quarantine Rules

```
                      +-----------------------------+
                      | Blood Collection Completed  |
                      +-----------------------------+
                                     |
                                     v
                       +---------------------------+
                       |    Status: QUARANTINED    | <---+ (Incomplete panel)
                       +---------------------------+     |
                                     |                   |
                        Infection Testing Results        |
                                     |                   |
            +------------------------+-------------------+
            |                                            |
            v (Any test = Fail)                          v (All 4 tests = Pass)
+------------------------+                  +---------------------------+
|    Status: DISCARDED   |                  |     Status: AVAILABLE     |
| (Blocked permanently)  |                  | (Expiry Date Calculated)  |
+------------------------+                  +---------------------------+
```

1. **Quarantined (Default)**:
   - When recorded via `BloodUnit.record_collection()`, the unit begins with `status = BloodUnitStatus.QUARANTINED`.
   - Units with incomplete tests (e.g. 1 to 3 tests recorded, or missing results) remain in `Quarantined`.
   - `BloodUnitQuerySet.available()` automatically filters out quarantined units from inventory metrics and requisition cross-matching.

2. **Available (All 4 Pass)**:
   - Requires all 4 mandatory infection screening tests (`HIV`, `Hepatitis B`, `Hepatitis C`, `Syphilis`) to be recorded with outcome `Pass`.
   - Automatically sets the unit's `expiry_date` at the exact moment of clearance:
     - Whole Blood / RBC: 42 days from collection
     - Platelets: 5 days from collection
     - Fresh Frozen Plasma: 365 days from collection
   - Validation guards in `clean()` reject any manual attempt to force status to `Available` without the required tests passing.

3. **Discarded (Any Single Fail)**:
   - If any test records `Fail` (reactive), the unit immediately transitions to `BloodUnitStatus.DISCARDED`.
   - Once a unit has a failed test, validation guards strictly reject any attempt to revert its status to `Quarantined` or `Available`.

---

## 3. Web UI & REST API Endpoints

### Staff Web UI
- **URL**: `/inventory/blood-units/<bag_id>/`
- Features the **Serology Testing Panel & Quarantine Controls** card.
- Displays the 4 mandatory tests with colored badges (`Pass` = Green, `Fail` = Red, `Pending` = Amber).
- Shows elapsed quarantine duration (in days) and audit history log.
- Staff Serology Entry Form submits to `POST /inventory/blood-units/<bag_id>/serology/`.

### REST API (SAD Section 4.3)
- **Endpoint**: `POST /api/blood-units/<bag_id>/serology/`
- **Access**: Staff / Admin (`BBMS-SR-003`)
- **Headers**: `Content-Type: application/json`
- **Request Payload**:
  ```json
  {
    "tests": {
      "HIV": "Pass",
      "Hepatitis B": "Pass",
      "Hepatitis C": "Pass",
      "Syphilis": "Pass"
    },
    "notes": "Automated ELISA screening analyzer run #104."
  }
  ```
- **Response Payload (200 OK)**:
  ```json
  {
    "status": "success",
    "message": "Serology test results recorded for unit BAG-20261022-A1B2C3. Current status: Available.",
    "bag_id": "BAG-20261022-A1B2C3",
    "unit_status": "Available",
    "is_available": true,
    "is_discarded": false,
    "is_quarantined": false,
    "expiry_date": "2026-12-03T00:00:00",
    "serology_tests": {
      "HIV": {"recorded": true, "result": "Pass", "tested_by": "staff_user", ...},
      "Hepatitis B": {"recorded": true, "result": "Pass", "tested_by": "staff_user", ...},
      "Hepatitis C": {"recorded": true, "result": "Pass", "tested_by": "staff_user", ...},
      "Syphilis": {"recorded": true, "result": "Pass", "tested_by": "staff_user", ...}
    }
  }
  ```

---

## 4. Verification & Testing

Run the automated serology and quarantine test suite:
```bash
python manage.py test inventory.tests.SerologyQuarantineTests --verbosity 2
```
