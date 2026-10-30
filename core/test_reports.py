"""
Automated Test Suite for Administrative Reports & CSV Analytics
(SRS BBMS-F-064 to BBMS-F-066, BBMS-SR-003, BBMS-SR-005, TC-RPT-01, TC-SEC-03).

Test Coverage:
1. TC-SEC-03: Server-side Role-Based Access Control (RBAC):
   - Anonymous users redirected to login (or 401 for API).
   - Unauthorized roles (DONOR, HOSPITAL, STAFF) denied with HTTP 403 Forbidden.
   - ADMIN and Superuser granted access (HTTP 200).
   - Applied across /reports/, CSV download endpoints, and /api/reports/.

2. TC-RPT-01: Inventory Stock Report & Safe Availability (BBMS-F-064):
   - Accurate stock breakdown by ABO/Rh blood groups, components, and storage locations.
   - Strict adherence to safe availability rules: Quarantined, Discarded, Expired,
     Allocated, and Dispatched units excluded from available stock.
   - CSV export generation and formatting verification.

3. TC-RPT-01: Donation Activity by Date Range (BBMS-F-065):
   - Validated date range filtering with inclusive boundaries.
   - Accurate calculation of total donations, collected units, and discarded units.
   - Explicit verification that child components separated from Whole Blood are NOT
     counted as new donations.
   - Discard reasons and blood group distributions.

4. TC-RPT-01: Requisition Fulfilment Accounting (BBMS-F-066):
   - Date range tracking of requisitions: Received, Fulfilled, Partially Fulfilled, Rejected.
   - Units requested vs dispatched accounting from persisted RequisitionFulfilment records.
   - Dispatch manifests issued metrics.

5. TC-RPT-01: Boundary Conditions, Formula Injection Safety & Privacy:
   - Date validation: invalid date formats and start_date > end_date handled cleanly.
   - Empty results handling: zero division prevented; graceful empty tables and valid CSVs.
   - Spreadsheet formula injection protection: values starting with '=', '+', '-', '@' sanitized.
   - Privacy protection: donor personal identifying information (PII) excluded.
"""

from datetime import date, timedelta
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from core.constants import BloodGroup
from core.reports import (
    generate_donations_csv,
    generate_inventory_csv,
    generate_requisitions_csv,
    get_donation_activity_report_data,
    get_inventory_report_data,
    get_requisition_report_data,
    parse_and_validate_date_range,
    sanitize_csv_cell,
)
from inventory.models import BloodUnit, BloodUnitStatus, ComponentType, DispatchManifest
from requisitions.models import Requisition, RequisitionFulfilment


class ReportsRBACTests(TestCase):
    """
    Test Case TC-SEC-03: Role-based authorization enforcement on reports screens and exports.
    SRS BBMS-SR-003, BBMS-F-064–F-066.
    """

    @classmethod
    def setUpTestData(cls):
        cls.admin_user = User.objects.create_user(
            username='admin_report_test',
            email='admin@bbms.test',
            password='TestPassword123!',
            role=User.Role.ADMIN,
        )
        cls.staff_user = User.objects.create_user(
            username='staff_report_test',
            email='staff@bbms.test',
            password='TestPassword123!',
            role=User.Role.STAFF,
        )
        cls.donor_user = User.objects.create_user(
            username='donor_report_test',
            email='donor@bbms.test',
            password='TestPassword123!',
            role=User.Role.DONOR,
        )
        cls.hospital_user = User.objects.create_user(
            username='hospital_report_test',
            email='hospital@bbms.test',
            password='TestPassword123!',
            role=User.Role.HOSPITAL,
            is_approved=True,
        )
        cls.superuser = User.objects.create_superuser(
            username='super_report_test',
            email='super@bbms.test',
            password='TestPassword123!',
        )

        cls.endpoints = [
            reverse('core:reports_dashboard'),
            reverse('core:export_inventory_csv'),
            reverse('core:export_donations_csv'),
            reverse('core:export_requisitions_csv'),
        ]

    def setUp(self):
        self.client = Client()

    def test_anonymous_access_redirects_to_login(self):
        """Unauthenticated requests must be redirected to login (SRS BBMS-SR-001)."""
        for url in self.endpoints:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 302)
                self.assertIn('/accounts/login/', response.url)

    def test_unauthorized_roles_denied_http_403(self):
        """
        Staff, Donors, and Hospital users must receive HTTP 403 Forbidden
        (SRS BBMS-SR-003, TC-SEC-03).
        """
        unauthorized_users = [self.donor_user, self.hospital_user, self.staff_user]

        for user in unauthorized_users:
            self.client.force_login(user)
            for url in self.endpoints:
                with self.subTest(user=user.username, url=url):
                    response = self.client.get(url)
                    self.assertEqual(response.status_code, 403)

    def test_admin_and_superuser_granted_access(self):
        """Admins and Superusers must receive HTTP 200 OK (SRS BBMS-SR-003)."""
        for authorized in [self.admin_user, self.superuser]:
            self.client.force_login(authorized)
            for url in self.endpoints:
                with self.subTest(user=authorized.username, url=url):
                    response = self.client.get(url)
                    self.assertEqual(response.status_code, 200)

    def test_api_reports_rbac(self):
        """REST API reports endpoint must enforce RBAC: 401 unauth, 403 unauthorized, 200 admin."""
        api_url = reverse('core:api_reports')

        # 1. Anonymous -> 401
        res = self.client.get(api_url, HTTP_ACCEPT='application/json')
        self.assertEqual(res.status_code, 401)

        # 2. Staff / Donor / Hospital -> 403
        for unauth in [self.staff_user, self.donor_user, self.hospital_user]:
            self.client.force_login(unauth)
            res = self.client.get(api_url, HTTP_ACCEPT='application/json')
            self.assertEqual(res.status_code, 403)

        # 3. Admin -> 200
        self.client.force_login(self.admin_user)
        res = self.client.get(api_url, HTTP_ACCEPT='application/json')
        self.assertEqual(res.status_code, 200)
        self.assertIn('inventory', res.json())


class InventoryStockReportTests(TestCase):
    """
    Test Case TC-RPT-01: Inventory stock reporting and safe availability rules.
    SRS BBMS-F-064, BBMS-F-028, BBMS-F-033, BBMS-F-039.
    """

    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user(
            username='admin_inv_rpt', email='admin_inv@bbms.test',
            password='TestPassword123!', role=User.Role.ADMIN,
        )
        cls.donor = User.objects.create_user(
            username='donor_inv_rpt', email='donor_inv@bbms.test',
            password='TestPassword123!', role=User.Role.DONOR,
        )
        now = timezone.now()

        # 1. Available units (safe)
        BloodUnit.objects.create(
            donor=cls.donor, blood_group=BloodGroup.A_POS, component_type=ComponentType.WHOLE_BLOOD,
            status=BloodUnitStatus.AVAILABLE, location='Central Blood Bank',
            collection_date=now - timedelta(days=2), expiry_date=now + timedelta(days=40),
        )
        BloodUnit.objects.create(
            donor=cls.donor, blood_group=BloodGroup.A_POS, component_type=ComponentType.RBC,
            status=BloodUnitStatus.AVAILABLE, location='Central Blood Bank',
            collection_date=now - timedelta(days=3), expiry_date=now + timedelta(days=30),
        )
        BloodUnit.objects.create(
            donor=cls.donor, blood_group=BloodGroup.O_NEG, component_type=ComponentType.PLATELETS,
            status=BloodUnitStatus.AVAILABLE, location='North Branch',
            collection_date=now - timedelta(days=1), expiry_date=now + timedelta(days=4),  # Expiring soon
        )

        # 2. Excluded units (Quarantined, Discarded, Expired, Separated, Dispatched)
        BloodUnit.objects.create(
            donor=cls.donor, blood_group=BloodGroup.A_POS, component_type=ComponentType.WHOLE_BLOOD,
            status=BloodUnitStatus.QUARANTINED, location='Central Blood Bank',
            collection_date=now, expiry_date=now + timedelta(days=42),
        )
        BloodUnit.objects.create(
            donor=cls.donor, blood_group=BloodGroup.B_POS, component_type=ComponentType.WHOLE_BLOOD,
            status=BloodUnitStatus.DISCARDED, location='Central Blood Bank',
            collection_date=now - timedelta(days=5), expiry_date=now + timedelta(days=37),
        )
        BloodUnit.objects.create(
            donor=cls.donor, blood_group=BloodGroup.O_POS, component_type=ComponentType.WHOLE_BLOOD,
            status=BloodUnitStatus.EXPIRED, location='Central Blood Bank',
            collection_date=now - timedelta(days=50), expiry_date=now - timedelta(days=5),
        )
        BloodUnit.objects.create(
            donor=cls.donor, blood_group=BloodGroup.AB_POS, component_type=ComponentType.WHOLE_BLOOD,
            status=BloodUnitStatus.DISPATCHED, location='Central Blood Bank',
            collection_date=now - timedelta(days=10), expiry_date=now + timedelta(days=30),
        )

    def test_safe_availability_rules_enforced_in_inventory_report(self):
        """
        Quarantined, Discarded, Expired, and Dispatched units must be strictly excluded
        from available inventory stock (BBMS-F-064, BBMS-F-028, BBMS-F-039).
        """
        data = get_inventory_report_data()

        # Available units: exactly 3
        self.assertEqual(data['total_available'], 3)
        self.assertEqual(data['total_quarantined'], 1)
        self.assertEqual(data['total_discarded'], 1)
        self.assertEqual(data['expiring_soon_count'], 1)

        # Verify stock matrix component totals
        grand = data['grand_component_totals']
        self.assertEqual(grand['whole_blood'], 1)
        self.assertEqual(grand['rbc'], 1)
        self.assertEqual(grand['platelets'], 1)
        self.assertEqual(grand['plasma'], 0)
        self.assertEqual(grand['total'], 3)

    def test_location_filtering_in_inventory_report(self):
        """Inventory report can be filtered by specific facility location."""
        north_data = get_inventory_report_data(location='North Branch')
        self.assertEqual(north_data['total_available'], 1)

        central_data = get_inventory_report_data(location='Central Blood Bank')
        self.assertEqual(central_data['total_available'], 2)

    def test_generate_inventory_csv(self):
        """Inventory CSV export contains safety summary and stock matrices."""
        csv_content = generate_inventory_csv()
        self.assertIn('BBMS INVENTORY STOCK REPORT', csv_content)
        self.assertIn('Total Available Units,3', csv_content)
        self.assertIn('Total Quarantined Units,1', csv_content)
        self.assertIn('Total Discarded Units,1', csv_content)
        self.assertIn('A+,1,1,0,0,2', csv_content)  # A+ has 1 WB + 1 RBC = 2
        self.assertIn('Central Blood Bank', csv_content)
        self.assertIn('North Branch', csv_content)

    def test_inventory_csv_download_view(self):
        """Admin can download the inventory CSV via GET /reports/inventory/csv/."""
        client = Client()
        client.force_login(self.admin)
        response = client.get(reverse('core:export_inventory_csv'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'text/csv; charset=utf-8')
        self.assertIn('attachment; filename="bbms_inventory_stock_', response['Content-Disposition'])
        self.assertIn('Total Available Units,3', response.content.decode('utf-8'))


class DonationActivityReportTests(TestCase):
    """
    Test Case TC-RPT-01: Donation activity reporting by date range.
    SRS BBMS-F-065.
    Rules:
    - Total donations: count of original donor collections (parent_unit is None).
    - Separated child components are NOT counted as new donations.
    - Collected units count primary units.
    - Discarded units count units discarded in the period.
    """

    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user(
            username='admin_don_rpt', email='admin_don@bbms.test',
            password='TestPassword123!', role=User.Role.ADMIN,
        )
        cls.donor1 = User.objects.create_user(
            username='donor_alice', email='alice@bbms.test',
            password='TestPassword123!', role=User.Role.DONOR,
        )
        cls.donor2 = User.objects.create_user(
            username='donor_bob', email='bob@bbms.test',
            password='TestPassword123!', role=User.Role.DONOR,
        )

        cls.base_date = timezone.localdate()
        today_dt = timezone.now()

        # Donation 1: 5 days ago by Alice (Available)
        cls.d1 = BloodUnit.objects.create(
            donor=cls.donor1, blood_group=BloodGroup.A_POS, component_type=ComponentType.WHOLE_BLOOD,
            status=BloodUnitStatus.AVAILABLE,
            collection_date=today_dt - timedelta(days=5),
        )

        # Donation 2: 3 days ago by Bob (Separated into 3 components!)
        cls.parent_wb = BloodUnit.objects.create(
            donor=cls.donor2, blood_group=BloodGroup.O_POS, component_type=ComponentType.WHOLE_BLOOD,
            status=BloodUnitStatus.SEPARATED,
            collection_date=today_dt - timedelta(days=3),
        )
        # 3 Child components from parent_wb
        cls.child_rbc = BloodUnit.objects.create(
            donor=cls.donor2, blood_group=BloodGroup.O_POS, component_type=ComponentType.RBC,
            parent_unit=cls.parent_wb, status=BloodUnitStatus.AVAILABLE,
            collection_date=cls.parent_wb.collection_date,
        )
        cls.child_plt = BloodUnit.objects.create(
            donor=cls.donor2, blood_group=BloodGroup.O_POS, component_type=ComponentType.PLATELETS,
            parent_unit=cls.parent_wb, status=BloodUnitStatus.DISCARDED,
            collection_date=cls.parent_wb.collection_date,
        )
        cls.child_plasma = BloodUnit.objects.create(
            donor=cls.donor2, blood_group=BloodGroup.O_POS, component_type=ComponentType.PLASMA,
            parent_unit=cls.parent_wb, status=BloodUnitStatus.AVAILABLE,
            collection_date=cls.parent_wb.collection_date,
        )

        # Donation 3: 2 days ago by Alice (Failed serology -> Discarded)
        cls.d3 = BloodUnit.objects.create(
            donor=cls.donor1, blood_group=BloodGroup.A_POS, component_type=ComponentType.WHOLE_BLOOD,
            status=BloodUnitStatus.DISCARDED,
            collection_date=today_dt - timedelta(days=2),
        )

        # Donation 4: 40 days ago (Outside default 30-day range)
        cls.old_donation = BloodUnit.objects.create(
            donor=cls.donor2, blood_group=BloodGroup.B_POS, component_type=ComponentType.WHOLE_BLOOD,
            status=BloodUnitStatus.AVAILABLE,
            collection_date=today_dt - timedelta(days=40),
        )

    def test_separated_components_are_not_new_donations(self):
        """
        SRS BBMS-F-065: Separated components must NOT be counted as new donations.
        In the last 7 days:
        - 3 primary donations occurred: d1, parent_wb, d3.
        - parent_wb was separated into 3 child components (rbc, plt, plasma).
        - Total donations must be exactly 3, NOT 6!
        """
        start = self.base_date - timedelta(days=7)
        end = self.base_date
        data = get_donation_activity_report_data(start, end)

        self.assertEqual(data['total_donations'], 3)
        self.assertEqual(data['collected_units'], 3)
        self.assertEqual(data['derived_components_count'], 3)
        self.assertEqual(data['unique_donors_count'], 2)

    def test_discarded_units_calculation(self):
        """
        Discarded units in the 7-day period must include both primary units (d3)
        and discarded separated components (child_plt).
        """
        start = self.base_date - timedelta(days=7)
        end = self.base_date
        data = get_donation_activity_report_data(start, end)

        # d3 (Whole blood) + child_plt (Platelets) = 2 discarded units
        self.assertEqual(data['discarded_units'], 2)

    def test_date_range_filtering_boundaries(self):
        """Events outside the date range must be excluded."""
        # 1. Past 30 days to today: includes d1, parent_wb, d3 (3 donations), excludes old_donation
        start_30 = self.base_date - timedelta(days=30)
        data_30 = get_donation_activity_report_data(start_30, self.base_date)
        self.assertEqual(data_30['total_donations'], 3)

        # 2. Past 60 days to today: includes all 4 donations
        start_60 = self.base_date - timedelta(days=60)
        data_60 = get_donation_activity_report_data(start_60, self.base_date)
        self.assertEqual(data_60['total_donations'], 4)

        # 3. Exact single day match for d1 (5 days ago)
        single_day = self.base_date - timedelta(days=5)
        data_single = get_donation_activity_report_data(single_day, single_day)
        self.assertEqual(data_single['total_donations'], 1)

    def test_generate_donations_csv(self):
        """Donations CSV export contains summary metrics, blood group breakdown, and no PII."""
        start = self.base_date - timedelta(days=7)
        end = self.base_date
        csv_text = generate_donations_csv(start, end)

        self.assertIn('BBMS DONATION ACTIVITY REPORT', csv_text)
        self.assertIn('Total Donations,3', csv_text)
        self.assertIn('Derived Components,3', csv_text)
        self.assertIn('Total Discarded Units,2', csv_text)
        # Excludes donor sensitive personal data
        self.assertNotIn('alice@bbms.test', csv_text)
        self.assertNotIn('bob@bbms.test', csv_text)

    def test_donations_csv_download_view(self):
        """Admin can download donations CSV via GET /reports/donations/csv/."""
        client = Client()
        client.force_login(self.admin)
        start = (self.base_date - timedelta(days=7)).strftime('%Y-%m-%d')
        end = self.base_date.strftime('%Y-%m-%d')

        response = client.get(f"{reverse('core:export_donations_csv')}?start_date={start}&end_date={end}")
        self.assertEqual(response.status_code, 200)
        self.assertIn('attachment; filename="bbms_donations_', response['Content-Disposition'])


class RequisitionFulfilmentReportTests(TestCase):
    """
    Test Case TC-RPT-01: Requisition and fulfilment accounting reports.
    SRS BBMS-F-066.
    """

    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user(
            username='admin_req_rpt', email='admin_req@bbms.test',
            password='TestPassword123!', role=User.Role.ADMIN,
        )
        cls.hospital = User.objects.create_user(
            username='hospital_city_general', email='city@hospital.test',
            password='TestPassword123!', role=User.Role.HOSPITAL, is_approved=True,
        )
        cls.donor = User.objects.create_user(
            username='donor_req_rpt', email='donor_req@bbms.test',
            password='TestPassword123!', role=User.Role.DONOR,
        )

        today = timezone.localdate()
        req_date = today + timedelta(days=2)

        # 1. Fulfilled Requisition (2 units requested, 2 units dispatched)
        cls.req_fulfilled = Requisition.objects.create(
            hospital=cls.hospital, blood_group=BloodGroup.A_POS,
            component_type=ComponentType.RBC, quantity=2, required_by=req_date,
            status=Requisition.Status.FULFILLED,
        )
        u1 = BloodUnit.objects.create(
            donor=cls.donor, blood_group=BloodGroup.A_POS, component_type=ComponentType.RBC,
            status=BloodUnitStatus.DISPATCHED,
        )
        u2 = BloodUnit.objects.create(
            donor=cls.donor, blood_group=BloodGroup.A_POS, component_type=ComponentType.RBC,
            status=BloodUnitStatus.DISPATCHED,
        )
        RequisitionFulfilment.objects.create(
            requisition=cls.req_fulfilled, blood_unit=u1, recorded_by=cls.admin,
        )
        RequisitionFulfilment.objects.create(
            requisition=cls.req_fulfilled, blood_unit=u2, recorded_by=cls.admin,
        )

        # 2. Partially Fulfilled Requisition (3 requested, 1 dispatched)
        cls.req_partial = Requisition.objects.create(
            hospital=cls.hospital, blood_group=BloodGroup.O_NEG,
            component_type=ComponentType.PLATELETS, quantity=3, required_by=req_date,
            status=Requisition.Status.PARTIALLY_FULFILLED,
        )
        u3 = BloodUnit.objects.create(
            donor=cls.donor, blood_group=BloodGroup.O_NEG, component_type=ComponentType.PLATELETS,
            status=BloodUnitStatus.DISPATCHED,
        )
        RequisitionFulfilment.objects.create(
            requisition=cls.req_partial, blood_unit=u3, recorded_by=cls.admin,
        )

        # 3. Rejected Requisition
        cls.req_rejected = Requisition.objects.create(
            hospital=cls.hospital, blood_group=BloodGroup.AB_NEG,
            component_type=ComponentType.WHOLE_BLOOD, quantity=1, required_by=req_date,
            status=Requisition.Status.REJECTED, rejection_reason='Out of stock in region.',
        )

        # 4. Pending Requisition
        cls.req_pending = Requisition.objects.create(
            hospital=cls.hospital, blood_group=BloodGroup.B_POS,
            component_type=ComponentType.RBC, quantity=2, required_by=req_date,
            status=Requisition.Status.PENDING,
        )

        # Dispatch Manifest
        manifest = DispatchManifest.objects.create(
            requisition=cls.req_fulfilled, dispatched_by=cls.admin, notes='Routine dispatch',
        )
        manifest.units.add(u1, u2)

    def test_requisition_totals_and_fulfilment_rates(self):
        """
        SRS BBMS-F-066: Accurately reports received, fulfilled, partially fulfilled,
        and rejected totals, and cumulative units dispatched.
        """
        today = timezone.localdate()
        data = get_requisition_report_data(today - timedelta(days=1), today + timedelta(days=1))

        self.assertEqual(data['total_received'], 4)
        self.assertEqual(data['total_fulfilled'], 1)
        self.assertEqual(data['total_partially_fulfilled'], 1)
        self.assertEqual(data['total_rejected'], 1)
        self.assertEqual(data['total_pending'], 1)
        self.assertEqual(data['total_approved'], 0)

        # Quantity calculations
        # 2 (fulfilled) + 3 (partial) + 1 (rejected) + 2 (pending) = 8 requested units
        self.assertEqual(data['total_units_requested'], 8)
        # Dispatched units from RequisitionFulfilment: 2 + 1 = 3
        self.assertEqual(data['total_units_dispatched'], 3)
        self.assertEqual(data['manifests_count'], 1)

        # Fulfilment rate: (1 fulfilled + 1 partial) / 4 received = 50.0%
        self.assertEqual(data['fulfilment_rate'], 50.0)

    def test_generate_requisitions_csv(self):
        """Requisitions CSV export contains totals and detail rows."""
        today = timezone.localdate()
        csv_text = generate_requisitions_csv(today - timedelta(days=1), today + timedelta(days=1))

        self.assertIn('BBMS REQUISITION & FULFILMENT REPORT', csv_text)
        self.assertIn('Total Received,4', csv_text)
        self.assertIn('Fulfilled,1', csv_text)
        self.assertIn('Partially Fulfilled,1', csv_text)
        self.assertIn('Rejected,1', csv_text)
        self.assertIn('Total Units Requested,8', csv_text)
        self.assertIn('Total Units Dispatched,3', csv_text)
        self.assertIn('Out of stock in region.', csv_text)


class ReportsValidationAndEdgeCaseTests(TestCase):
    """
    Test Case TC-RPT-01: Validation, empty results, formula safety, and privacy protections.
    SRS BBMS-SR-005, BBMS-F-064–F-066.
    """

    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user(
            username='admin_edge_test', email='admin_edge@bbms.test',
            password='TestPassword123!', role=User.Role.ADMIN,
        )

    def setUp(self):
        self.client = Client()
        self.client.force_login(self.admin)

    def test_date_range_validation_start_after_end(self):
        """Invalid date range where start_date > end_date returns validation error."""
        start, end, error = parse_and_validate_date_range('2026-10-30', '2026-10-01')
        self.assertIsNone(start)
        self.assertIsNone(end)
        self.assertIn('cannot be after end date', error)

        # View renders alert message
        res = self.client.get(reverse('core:reports_dashboard'), {'start_date': '2026-10-30', 'end_date': '2026-10-01'})
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'Date Range Validation Error')

        # CSV export returns 400 Bad Request
        csv_res = self.client.get(
            reverse('core:export_donations_csv'),
            {'start_date': '2026-10-30', 'end_date': '2026-10-01'}
        )
        self.assertEqual(csv_res.status_code, 400)

    def test_date_range_validation_malformed_string(self):
        """Malformed date strings return validation error."""
        start, end, error = parse_and_validate_date_range('not-a-date', '2026-10-30')
        self.assertIsNone(start)
        self.assertIn('Invalid start date format', error)

    def test_date_range_default_when_empty(self):
        """Empty date strings default to past 30 days up to today."""
        start, end, error = parse_and_validate_date_range('', '')
        self.assertIsNone(error)
        self.assertEqual(end, timezone.localdate())
        self.assertEqual(start, timezone.localdate() - timedelta(days=30))

    def test_empty_results_handling_without_errors(self):
        """When zero records exist in date range, renders cleanly without 500 error."""
        # Far future date range with 0 records
        future_start = date(2040, 1, 1)
        future_end = date(2040, 1, 31)

        donations = get_donation_activity_report_data(future_start, future_end)
        self.assertEqual(donations['total_donations'], 0)
        self.assertEqual(donations['collected_units'], 0)
        self.assertEqual(donations['discarded_units'], 0)

        reqs = get_requisition_report_data(future_start, future_end)
        self.assertEqual(reqs['total_received'], 0)
        self.assertEqual(reqs['fulfilment_rate'], 0.0)

        # CSV generation with 0 records succeeds cleanly
        don_csv = generate_donations_csv(future_start, future_end)
        self.assertIn('No collections recorded in this date range.', don_csv)

        req_csv = generate_requisitions_csv(future_start, future_end)
        self.assertIn('No requisitions recorded in this date range.', req_csv)

    def test_csv_formula_injection_mitigation(self):
        """
        Spreadsheet Formula Injection mitigation:
        Cells starting with '=', '+', '-', '@', '\\t', '\\r' must be prefixed with a single quote.
        SRS BBMS-SR-005.
        """
        dangerous_values = [
            ('=1+1', "''=1+1"),
            ('+cmd|calc', "'+cmd|calc"),
            ('-100', "'-100"),
            ('@SUM(A1:A10)', "'@SUM(A1:A10)"),
            ('\tTabbed', "'\tTabbed"),
            ('Safe Text', 'Safe Text'),
            (42, '42'),
            (None, ''),
        ]

        for raw, expected in dangerous_values:
            with self.subTest(raw=raw):
                if raw == '=1+1':
                    self.assertEqual(sanitize_csv_cell(raw), "'=1+1")
                else:
                    self.assertEqual(sanitize_csv_cell(raw), expected)

    def test_privacy_protection_donor_pii_excluded(self):
        """
        SRS BBMS-SR-005: Reports and CSV exports must exclude unnecessary donor personal data.
        Donor phone number, address, and password hash must NEVER appear in output.
        """
        donor = User.objects.create_user(
            username='sensitive_donor',
            email='sensitive@example.com',
            password='TestPassword123!',
            phone='9876543210',
            address='123 Secret Lane, Confidential City',
            role=User.Role.DONOR,
        )
        BloodUnit.objects.create(
            donor=donor,
            blood_group=BloodGroup.O_POS,
            component_type=ComponentType.WHOLE_BLOOD,
            status=BloodUnitStatus.AVAILABLE,
            collection_date=timezone.now(),
        )

        today = timezone.localdate()
        csv_text = generate_donations_csv(today - timedelta(days=1), today + timedelta(days=1))

        self.assertNotIn('9876543210', csv_text)
        self.assertNotIn('123 Secret Lane', csv_text)
        self.assertNotIn('sensitive@example.com', csv_text)
        self.assertNotIn('TestPassword123!', csv_text)
