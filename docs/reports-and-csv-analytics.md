# Administrative Reports & CSV Analytics Module

**SRS References:** Section 4.22 (BBMS-F-064, BBMS-F-065, BBMS-F-066), Section 5.1.2 (BBMS-SR-003), Section 5.1.5 (BBMS-SR-005)  
**STP Test Cases:** `TC-RPT-01`, `TC-SEC-03`  
**SAD References:** Section 3.9 (Security & Role-Based Access Control), Section 4.3 (REST API Architecture)  
**GitHub Issue:** [#42 (Inventory, donation and requisition reports)](https://github.com/SE-Blood-Bank-Management-System/Blood-Bank-Management-System/issues/42)  
**Assigned Owner:** Akshay Arcot (`@Akshayarcot` / PES1UG24CS705)

---

## 1. Overview & Requirements Traceability

The **Administrative Reports & CSV Analytics** module provides authorized blood bank administrators with centralized, real-time activity and stock reports, interactive date range filtering, and formula-safe CSV downloads.

| Requirement ID | Summary | Technical Implementation | Verified By |
| :--- | :--- | :--- | :--- |
| **BBMS-F-064** | Current inventory aggregation for group, component, and storage location stock with CSV export; adheres strictly to safe availability rules. | `get_inventory_report_data()`, `generate_inventory_csv()`, `BloodUnit.objects.available()` | `TC-RPT-01` |
| **BBMS-F-065** | Donation activity reports by validated date range (total donations, collected units, discarded units); separated child components are strictly excluded from new donation counts. | `get_donation_activity_report_data()`, `generate_donations_csv()`, `parent_unit__isnull=True` | `TC-RPT-01` |
| **BBMS-F-066** | Requisition activity reports by validated date range (received, fulfilled, partially fulfilled, rejected totals) from persisted request and dispatch records. | `get_requisition_report_data()`, `generate_requisitions_csv()`, `RequisitionFulfilment`, `DispatchManifest` | `TC-RPT-01` |
| **BBMS-SR-003** | Server-side role-based access control (RBAC) restricting screens, CSV exports, and API endpoints strictly to Administrators (`ADMIN`). | `@role_required(User.Role.ADMIN)`, `accounts.rbac.PERM_GENERATE_REPORTS` | `TC-SEC-03` |
| **BBMS-SR-005** | CSV Formula Injection (Spreadsheet Injection) mitigation and donor privacy protection (exclusion of unnecessary personal identifying information). | `sanitize_csv_cell()` prepending single quotes (`'`) to `=, +, -, @, \t, \r`, PII exclusion | `TC-RPT-01` |

---

## 2. Architecture & Data Flow

```
+----------------------------------------------------------------------------------------------------+
|                                    Administrator HTTP Requests                                     |
|  UI: /reports/       CSV: /reports/{inventory|donations|requisitions}/csv/       API: /api/reports/ |
+----------------------------------------------------------------------------------------------------+
                                                  |
                                                  v
+----------------------------------------------------------------------------------------------------+
|                                   Security & RBAC Layer (TC-SEC-03)                                 |
|                               @role_required(User.Role.ADMIN)                                      |
|                 (Unauthorized Donor / Hospital / Staff -> HTTP 403 Forbidden)                       |
+----------------------------------------------------------------------------------------------------+
                                                  |
                                                  v
+----------------------------------------------------------------------------------------------------+
|                                Date Range Validation Engine (TC-RPT-01)                             |
|                        parse_and_validate_date_range(start_date, end_date)                         |
|                 - Validates ISO YYYY-MM-DD format                                                  |
|                 - Asserts start_date <= end_date (Graceful 400 / Alert on inversion)              |
|                 - Inclusive timezone boundaries (00:00:00 to 23:59:59.999999)                      |
|                 - Sensible defaults (last 30 days) when parameters are omitted                      |
+----------------------------------------------------------------------------------------------------+
                                                  |
                     +----------------------------+----------------------------+
                     |                                                         |
                     v                                                         v
+-----------------------------------------+               +-----------------------------------------+
|      Business Analytics Services        |               |       Formula-Safe CSV Generators       |
|          (`core/reports.py`)            |               |           (`core/reports.py`)           |
|  - get_inventory_report_data()          |               |  - generate_inventory_csv()             |
|    * Reuses get_inventory_counts()      |               |  - generate_donations_csv()             |
|    * Safe availability rules            |               |  - generate_requisitions_csv()          |
|  - get_donation_activity_report_data()  |               |  * Prepends "'" to cells with =, +, -, @|
|    * parent_unit__isnull=True           |               |  * Excludes donor phone, email, address |
|  - get_requisition_report_data()        |               |  * Returns standard RFC 4180 CSV        |
+-----------------------------------------+               +-----------------------------------------+
```

---

## 3. Core Capabilities & Domain Rules

### 3.1 Inventory Stock Report (BBMS-F-064)
- **Safe Availability Guarantees**:
  Reuses `inventory.services.get_inventory_counts()`, enforcing that only `BloodUnit.objects.available()` are counted in active stock.
  Units in `QUARANTINED`, `DISCARDED`, `EXPIRED`, `ALLOCATED`, `DISPATCHED`, or `DELIVERED` status are strictly excluded from available counts.
- **Dimensional Breakdowns**:
  1. *ABO/Rh Blood Group & Component Matrix*: Cross-tabular breakdown of Whole Blood, Red Blood Cells, Platelets, and Fresh Frozen Plasma across all 8 blood groups.
  2. *Storage Facility Location Matrix*: Cross-tabular breakdown of blood group inventory at each blood bank and storage facility.
  3. *Safety Metrics*: Available units, Quarantined units (under testing), Discarded units (biohazard/serology failure), and 7-day FEFO Expiring Soon warnings.

### 3.2 Donation Activity Report (BBMS-F-065)
- **Component Separation Accounting**:
  When a Whole Blood unit is separated into derived components (Red Blood Cells, Platelets, Plasma), the derived units carry `parent_unit != None`.
  Per **BBMS-F-065**, separated components are **not new donations**.
  The report engine filters `parent_unit__isnull=True` to accurately count original donor collections. Derived child components are reported as a distinct secondary metric to provide full visibility without inflating collection figures.
- **Discarded Units Tracking**:
  Captures both units collected in the period that were discarded, and units that transitioned to `Discarded` via `StatusChange` records during the date range.

### 3.3 Requisition & Fulfilment Accounting (BBMS-F-066)
- **Status Lifecycle Metrics**:
  Categorizes hospital requisitions submitted during the date range into `Received`, `Fulfilled`, `Partially Fulfilled`, `Rejected`, `Pending`, and `Approved`.
- **Cumulative Fulfilment Accounting**:
  Calculates total requested blood units vs actual units dispatched based on immutable, append-only `RequisitionFulfilment` records and `DispatchManifest` audit documents.

### 3.4 Security, Formula Safety & Privacy (BBMS-SR-003, BBMS-SR-005, TC-SEC-03)
- **Strict RBAC Enforcement**:
  Every view, CSV download, and API endpoint is guarded by `@role_required(User.Role.ADMIN)`. Unauthenticated users are redirected to login (or 401 for API); non-admin roles (`DONOR`, `HOSPITAL`, `STAFF`) are denied with HTTP 403 Forbidden.
- **Spreadsheet Formula Injection Neutralization**:
  Any CSV cell starting with executable trigger characters (`=`, `+`, `-`, `@`, `\t`, `\r`) is prepended with a single quote (`'`), preventing malicious formula execution when opened in Microsoft Excel, Google Sheets, or LibreOffice Calc.
- **Privacy Compliance**:
  Reports and exports contain operational references (Bag IDs, Requisition IDs, hospital names, dates, statuses), strictly excluding donor personally identifying information (phone numbers, email addresses, national IDs, residential addresses, passwords, medical questionnaire responses).

---

## 4. Endpoints & URL Mapping

| Endpoint | Method | Role | Description |
| :--- | :--- | :--- | :--- |
| `/reports/` | GET | `ADMIN` | Administrative Reports Dashboard with interactive tabs, filters, and metric cards. |
| `/reports/inventory/csv/` | GET | `ADMIN` | Formula-safe CSV download of current inventory stock by group, component, and location. |
| `/reports/donations/csv/` | GET | `ADMIN` | Formula-safe CSV download of donation and collection activity for `start_date` to `end_date`. |
| `/reports/requisitions/csv/` | GET | `ADMIN` | Formula-safe CSV download of requisition fulfilment tracking for `start_date` to `end_date`. |
| `/api/reports/` | GET | `ADMIN` | REST API returning JSON reports for programmatic inspection (`?type=all|inventory|donations|requisitions`). |

---

## 5. Verification Evidence (TC-RPT-01, TC-SEC-03)

The automated test suite in `core/test_reports.py` comprises 21 test cases executing with 100% pass rate:

- `test_anonymous_access_redirects_to_login`: Verifies HTTP 302 login redirects for unauthenticated requests.
- `test_unauthorized_roles_denied_http_403`: Verifies HTTP 403 Forbidden for Donor, Hospital, and Staff roles across all endpoints.
- `test_admin_and_superuser_granted_access`: Verifies HTTP 200 OK for Admin and Superuser accounts.
- `test_api_reports_rbac`: Verifies 401, 403, and 200 responses on `/api/reports/`.
- `test_safe_availability_rules_enforced_in_inventory_report`: Verifies strict exclusion of Quarantined, Discarded, Expired, and Dispatched units from inventory counts.
- `test_location_filtering_in_inventory_report`: Verifies facility-level filtering.
- `test_generate_inventory_csv`: Verifies inventory CSV formatting and matrix contents.
- `test_separated_components_are_not_new_donations`: Verifies that Whole Blood unit separation into 3 child components does NOT inflate the total donations count.
- `test_discarded_units_calculation`: Verifies accurate discard counting.
- `test_date_range_filtering_boundaries`: Verifies inclusive date filtering and boundary precision.
- `test_generate_donations_csv`: Verifies donation CSV output and absence of donor PII.
- `test_requisition_totals_and_fulfilment_rates`: Verifies received, fulfilled, partially fulfilled, and rejected accounting.
- `test_generate_requisitions_csv`: Verifies requisition CSV generation and status tracking.
- `test_date_range_validation_start_after_end`: Verifies error handling when `start_date > end_date`.
- `test_date_range_validation_malformed_string`: Verifies rejection of invalid date strings.
- `test_date_range_default_when_empty`: Verifies 30-day default fallback.
- `test_empty_results_handling_without_errors`: Verifies zero division prevention and graceful empty state handling.
- `test_csv_formula_injection_mitigation`: Verifies formula prefix escaping (`=`, `+`, `-`, `@`, `\t`, `\r`).
- `test_privacy_protection_donor_pii_excluded`: Verifies that donor sensitive fields are absent from exported files.
