"""
Unit and integration tests for Blood Inventory Dashboard and Search/Filter.

SRS References:
- Section 4.7 (BBMS-F-022, BBMS-F-023): Blood Group Management
- Section 4.8, 4.9 (BBMS-F-024 to BBMS-F-030): Serology & Quarantine Exclusion
- Section 4.11 (BBMS-F-033 to BBMS-F-036): Blood Inventory Management
- Section 4.12 (BBMS-F-037 to BBMS-F-039): Expiry Handling & FEFO
- Section 5.1 (BBMS-NF-001): Sub-2-second response time

Test Plan:
- TC-INV-01: Inventory counts, location grouping, and FEFO expiry exclusion
- TC-INV-02: Inventory availability count updates after serology transitions
"""
import time
from datetime import timedelta
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from core.constants import BloodGroup, VALID_BLOOD_GROUPS
from inventory.models import (
    BloodUnit,
    BloodUnitStatus,
    ComponentType,
    REQUIRED_SEROLOGY_TESTS,
    SerologyResult,
    SerologyTestType,
)
from inventory.services import get_inventory_counts, filter_and_search_inventory


class InventoryDashboardTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        # 1. User accounts
        cls.staff = User.objects.create_user(
            username='inv_staff',
            email='staff@bbms.local',
            role=User.Role.STAFF,
            first_name='John',
            last_name='Staff'
        )
        cls.admin = User.objects.create_user(
            username='inv_admin',
            email='admin@bbms.local',
            role=User.Role.ADMIN
        )
        cls.donor = User.objects.create_user(
            username='inv_donor',
            email='donor@bbms.local',
            role=User.Role.DONOR,
            first_name='Alice',
            last_name='Donor',
            blood_group='O+'
        )
        cls.hospital = User.objects.create_user(
            username='inv_hospital',
            email='hospital@bbms.local',
            role=User.Role.HOSPITAL
        )

        now = timezone.now()

        # 2. Seed units across locations and statuses
        # Location 1: Central Blood Bank
        cls.u_avail_o_pos = BloodUnit.objects.create(
            bag_id='BAG-TEST-001',
            donor=cls.donor,
            blood_group=BloodGroup.O_POS,
            status=BloodUnitStatus.AVAILABLE,
            component_type=ComponentType.WHOLE_BLOOD,
            volume_ml=450,
            location='Central Blood Bank',
            collection_date=now - timedelta(days=2),
            expiry_date=now + timedelta(days=40),
            collected_by=cls.staff,
        )

        cls.u_avail_a_pos = BloodUnit.objects.create(
            bag_id='BAG-TEST-002',
            donor=cls.donor,
            blood_group=BloodGroup.A_POS,
            status=BloodUnitStatus.AVAILABLE,
            component_type=ComponentType.RBC,
            volume_ml=300,
            location='Central Blood Bank',
            collection_date=now - timedelta(days=3),
            expiry_date=now + timedelta(days=5),  # Expiring soon (within 7 days)
            collected_by=cls.staff,
        )

        cls.u_quarantined = BloodUnit.objects.create(
            bag_id='BAG-TEST-003',
            donor=cls.donor,
            blood_group=BloodGroup.B_POS,
            status=BloodUnitStatus.QUARANTINED,
            component_type=ComponentType.WHOLE_BLOOD,
            volume_ml=450,
            location='Central Blood Bank',
            collection_date=now - timedelta(hours=5),
            collected_by=cls.staff,
        )

        cls.u_discarded = BloodUnit.objects.create(
            bag_id='BAG-TEST-004',
            donor=cls.donor,
            blood_group=BloodGroup.AB_POS,
            status=BloodUnitStatus.DISCARDED,
            component_type=ComponentType.WHOLE_BLOOD,
            volume_ml=450,
            location='Central Blood Bank',
            collection_date=now - timedelta(days=1),
            collected_by=cls.staff,
        )

        # Location 2: City Hospital Wing
        cls.u_city_avail = BloodUnit.objects.create(
            bag_id='BAG-TEST-005',
            donor=cls.donor,
            blood_group=BloodGroup.O_NEG,
            status=BloodUnitStatus.AVAILABLE,
            component_type=ComponentType.PLATELETS,
            volume_ml=250,
            location='City Hospital Wing',
            collection_date=now - timedelta(days=1),
            expiry_date=now + timedelta(days=4),
            collected_by=cls.staff,
        )

        # Expired unit (was Available, but expiry passed)
        cls.u_expired = BloodUnit.objects.create(
            bag_id='BAG-TEST-006',
            donor=cls.donor,
            blood_group=BloodGroup.O_POS,
            status=BloodUnitStatus.AVAILABLE,
            component_type=ComponentType.WHOLE_BLOOD,
            volume_ml=450,
            location='Central Blood Bank',
            collection_date=now - timedelta(days=50),
            expiry_date=now - timedelta(days=2),
            collected_by=cls.staff,
        )

    def setUp(self):
        self.dashboard_url = reverse('inventory:dashboard')
        self.api_inventory_url = reverse('inventory:api_inventory')
        self.client.force_login(self.staff)

    # -------------------------------------------------------------------------
    # RBAC & Access Control Tests
    # -------------------------------------------------------------------------
    def test_unauthenticated_access_redirected(self):
        """Unauthenticated requests to the dashboard are redirected to login."""
        self.client.logout()
        response = self.client.get(self.dashboard_url)
        self.assertEqual(response.status_code, 302)
        self.assertIn('/accounts/login/', response.url)

    def test_donor_access_denied(self):
        """Donors cannot access the staff inventory dashboard or API."""
        self.client.force_login(self.donor)
        response = self.client.get(self.dashboard_url)
        # role_required redirects or denies unauthorized roles
        self.assertIn(response.status_code, [302, 403])

        # API denial
        api_resp = self.client.get(self.api_inventory_url)
        self.assertIn(api_resp.status_code, [302, 403])

    def test_hospital_access_denied(self):
        """Hospital users cannot access the staff inventory dashboard or API."""
        self.client.force_login(self.hospital)
        response = self.client.get(self.dashboard_url)
        self.assertIn(response.status_code, [302, 403])

    def test_staff_and_admin_access_allowed(self):
        """Staff and Admin users successfully access the dashboard with HTTP 200."""
        response = self.client.get(self.dashboard_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Blood Inventory Dashboard")

        self.client.force_login(self.admin)
        response_admin = self.client.get(self.dashboard_url)
        self.assertEqual(response_admin.status_code, 200)

    # -------------------------------------------------------------------------
    # TC-INV-01: Inventory counts, location grouping & FEFO metrics
    # -------------------------------------------------------------------------
    def test_tc_inv_01_inventory_counts_grouped_by_blood_group_and_location(self):
        """
        TC-INV-01: Verify available blood-unit counts grouped by blood group and location.
        Confirm Quarantined, Discarded, and Expired units are excluded from available counts.
        SRS BBMS-F-028, BBMS-F-033, BBMS-F-034, BBMS-F-037.
        """
        counts = get_inventory_counts()

        # Available units: BAG-TEST-001 (O+), BAG-TEST-002 (A+), BAG-TEST-005 (O-) -> Total = 3
        # Excluded: BAG-TEST-003 (Quarantined), BAG-TEST-004 (Discarded), BAG-TEST-006 (Expired)
        self.assertEqual(counts['total_units_available'], 3)
        self.assertEqual(counts['quarantined_units'], 1)
        self.assertEqual(counts['discarded_units'], 1)

        # Expiring soon (within 7 days): BAG-TEST-002 (in 5d), BAG-TEST-005 (in 4d) -> Total = 2
        self.assertEqual(counts['expiring_soon_count'], 2)

        # Check location matrix
        loc_map = {row['location']: row for row in counts['location_matrix']}
        self.assertIn('Central Blood Bank', loc_map)
        self.assertIn('City Hospital Wing', loc_map)

        # Central Blood Bank counts: O+ (1), A+ (1), total = 2
        central_row = loc_map['Central Blood Bank']
        self.assertEqual(central_row['counts'][BloodGroup.O_POS], 1)
        self.assertEqual(central_row['counts'][BloodGroup.A_POS], 1)
        self.assertEqual(central_row['counts'][BloodGroup.B_POS], 0)  # B+ is quarantined!
        self.assertEqual(central_row['counts'][BloodGroup.AB_POS], 0)  # AB+ is discarded!
        self.assertEqual(central_row['total'], 2)

        # City Hospital Wing counts: O- (1), total = 1
        city_row = loc_map['City Hospital Wing']
        self.assertEqual(city_row['counts'][BloodGroup.O_NEG], 1)
        self.assertEqual(city_row['total'], 1)

        # Verify Grand totals
        self.assertEqual(counts['loc_grand_totals']['all'], 3)
        self.assertEqual(counts['loc_grand_totals'][BloodGroup.O_POS], 1)
        self.assertEqual(counts['loc_grand_totals'][BloodGroup.A_POS], 1)
        self.assertEqual(counts['loc_grand_totals'][BloodGroup.O_NEG], 1)

        # Dashboard HTML contains location grouping table
        response = self.client.get(self.dashboard_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Central Blood Bank')
        self.assertContains(response, 'City Hospital Wing')
        self.assertContains(response, 'Stock by Location &amp; Blood Group')

    # -------------------------------------------------------------------------
    # TC-INV-02: Inventory availability count updates after serology transitions
    # -------------------------------------------------------------------------
    def test_tc_inv_02_counts_update_after_unit_becomes_available(self):
        """
        TC-INV-02: Verify inventory counts increase when a unit transitions to Available
        following successful serology testing, and verify Quarantined units stay excluded until cleared.
        SRS BBMS-F-026, BBMS-F-033, BBMS-F-036.
        """
        # Baseline count for B+ at Central Blood Bank is 0
        baseline_counts = get_inventory_counts(location='Central Blood Bank')
        b_pos_row = next(r for r in baseline_counts['stock_matrix'] if r['blood_group'] == BloodGroup.B_POS)
        self.assertEqual(b_pos_row['total'], 0)
        self.assertEqual(baseline_counts['total_units_available'], 2)

        # Now execute serology panel with all passing tests on u_quarantined (B+)
        pass_panel = {
            SerologyTestType.HIV: SerologyResult.PASS,
            SerologyTestType.HEPATITIS_B: SerologyResult.PASS,
            SerologyTestType.HEPATITIS_C: SerologyResult.PASS,
            SerologyTestType.SYPHILIS: SerologyResult.PASS,
        }
        self.u_quarantined.record_serology_panel(pass_panel, staff_user=self.staff)
        self.u_quarantined.refresh_from_db()

        # Unit status transitioned to Available
        self.assertEqual(self.u_quarantined.status, BloodUnitStatus.AVAILABLE)
        self.assertTrue(self.u_quarantined.is_available)

        # Verify inventory counts automatically incremented
        updated_counts = get_inventory_counts(location='Central Blood Bank')
        updated_b_pos_row = next(r for r in updated_counts['stock_matrix'] if r['blood_group'] == BloodGroup.B_POS)
        self.assertEqual(updated_b_pos_row['total'], 1)
        self.assertEqual(updated_counts['total_units_available'], 3)

        # Verify location matrix reflects the newly available B+ unit
        loc_map = {row['location']: row for row in updated_counts['location_matrix']}
        self.assertEqual(loc_map['Central Blood Bank']['counts'][BloodGroup.B_POS], 1)
        self.assertEqual(loc_map['Central Blood Bank']['total'], 3)

        # Test failure scenario: failing a test transitions to Discarded and decrements count
        self.u_quarantined.record_serology_test(
            SerologyTestType.HIV,
            SerologyResult.FAIL,
            staff_user=self.staff,
            notes='Confirmatory reactive sample'
        )
        self.u_quarantined.refresh_from_db()
        self.assertEqual(self.u_quarantined.status, BloodUnitStatus.DISCARDED)

        # Counts must automatically exclude it again
        post_discard_counts = get_inventory_counts(location='Central Blood Bank')
        self.assertEqual(post_discard_counts['total_units_available'], 2)

    # -------------------------------------------------------------------------
    # Filtering and Search Tests
    # -------------------------------------------------------------------------
    def test_filter_by_blood_group(self):
        """Staff can filter the inventory listing by ABO/Rh blood group."""
        response = self.client.get(self.dashboard_url, {'blood_group': 'A+'})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'BAG-TEST-002')
        self.assertNotContains(response, 'BAG-TEST-001')
        self.assertNotContains(response, 'BAG-TEST-005')

    def test_filter_by_status(self):
        """Staff can filter the inventory listing by status."""
        # 1. Filter Quarantined
        resp_q = self.client.get(self.dashboard_url, {'status': 'Quarantined'})
        self.assertEqual(resp_q.status_code, 200)
        self.assertContains(resp_q, 'BAG-TEST-003')
        self.assertNotContains(resp_q, 'BAG-TEST-001')

        # 2. Filter Discarded
        resp_d = self.client.get(self.dashboard_url, {'status': 'Discarded'})
        self.assertEqual(resp_d.status_code, 200)
        self.assertContains(resp_d, 'BAG-TEST-004')
        self.assertNotContains(resp_d, 'BAG-TEST-001')

    def test_filter_by_location(self):
        """Staff can filter the inventory listing by location."""
        response = self.client.get(self.dashboard_url, {'location': 'City Hospital Wing'})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'BAG-TEST-005')
        self.assertNotContains(response, 'BAG-TEST-001')

    def test_filter_by_component_type(self):
        """Staff can filter the inventory listing by component type."""
        response = self.client.get(self.dashboard_url, {'component_type': 'Platelets'})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'BAG-TEST-005')
        self.assertNotContains(response, 'BAG-TEST-001')

    def test_search_by_bag_id(self):
        """Staff can search blood unit records by Bag ID."""
        response = self.client.get(self.dashboard_url, {'q': 'TEST-002'})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'BAG-TEST-002')
        self.assertNotContains(response, 'BAG-TEST-001')
        self.assertNotContains(response, 'BAG-TEST-005')

    def test_search_by_donor_username_or_name(self):
        """Staff can search blood unit records by donor name or username."""
        response = self.client.get(self.dashboard_url, {'q': 'Alice'})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'BAG-TEST-001')
        self.assertContains(response, 'BAG-TEST-002')

    # -------------------------------------------------------------------------
    # REST API Endpoint Tests (SAD Section 4.3)
    # -------------------------------------------------------------------------
    def test_api_inventory_get_structure(self):
        """
        GET /api/inventory/ returns valid JSON with summary metrics,
        location matrix, blood group breakdown, and paginated unit list.
        """
        response = self.client.get(self.api_inventory_url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers['content-type'], 'application/json')

        data = response.json()
        self.assertEqual(data['status'], 'success')
        self.assertIn('summary', data)
        self.assertEqual(data['summary']['total_available'], 3)
        self.assertEqual(data['summary']['total_quarantined'], 1)
        self.assertEqual(data['summary']['total_discarded'], 1)

        self.assertIn('by_blood_group', data)
        self.assertIn('by_location', data)
        self.assertIn('results', data)
        self.assertIn('pagination', data)

        # Inspect unit serialization
        first_unit = data['results'][0]
        self.assertIn('bag_id', first_unit)
        self.assertIn('blood_group', first_unit)
        self.assertIn('status', first_unit)
        self.assertIn('component_type', first_unit)
        self.assertIn('location', first_unit)

    def test_api_inventory_query_filtering(self):
        """REST API supports blood_group, status, and search query parameters."""
        # 1. Filter by blood group
        resp = self.client.get(self.api_inventory_url, {'blood_group': 'A+'})
        data = resp.json()
        self.assertEqual(data['pagination']['total_count'], 1)
        self.assertEqual(data['results'][0]['bag_id'], 'BAG-TEST-002')

        # 2. Search query
        resp_q = self.client.get(self.api_inventory_url, {'q': 'TEST-005'})
        data_q = resp_q.json()
        self.assertEqual(data_q['pagination']['total_count'], 1)
        self.assertEqual(data_q['results'][0]['bag_id'], 'BAG-TEST-005')

    # -------------------------------------------------------------------------
    # Performance Benchmark (BBMS-NF-001)
    # -------------------------------------------------------------------------
    def test_inventory_listing_and_search_under_two_seconds(self):
        """
        Inventory listing and search respond in under two seconds
        under expected test conditions (SRS BBMS-NF-001, Acceptance Criteria).
        """
        # Create additional test units
        bulk_units = []
        now = timezone.now()
        for i in range(50):
            bg = VALID_BLOOD_GROUPS[i % len(VALID_BLOOD_GROUPS)]
            bulk_units.append(
                BloodUnit(
                    bag_id=f'BAG-PERF-{i:04d}',
                    donor=self.donor,
                    blood_group=bg,
                    status=BloodUnitStatus.AVAILABLE,
                    component_type=ComponentType.WHOLE_BLOOD,
                    volume_ml=450,
                    location='Central Blood Bank' if i % 2 == 0 else 'City Hospital Wing',
                    collection_date=now - timedelta(days=i),
                    expiry_date=now + timedelta(days=40),
                )
            )
        BloodUnit.objects.bulk_create(bulk_units)

        # Benchmark 1: Dashboard HTML load
        start = time.perf_counter()
        resp_dash = self.client.get(self.dashboard_url)
        elapsed_dash = time.perf_counter() - start
        self.assertEqual(resp_dash.status_code, 200)
        self.assertLess(elapsed_dash, 2.0, f"Dashboard load took {elapsed_dash:.3f}s; expected < 2.0s")

        # Benchmark 2: Search and filtering
        start = time.perf_counter()
        resp_search = self.client.get(self.dashboard_url, {'q': 'PERF-001', 'blood_group': 'O+'})
        elapsed_search = time.perf_counter() - start
        self.assertEqual(resp_search.status_code, 200)
        self.assertLess(elapsed_search, 2.0, f"Search query took {elapsed_search:.3f}s; expected < 2.0s")

        # Benchmark 3: REST API endpoint
        start = time.perf_counter()
        resp_api = self.client.get(self.api_inventory_url, {'location': 'Central Blood Bank'})
        elapsed_api = time.perf_counter() - start
        self.assertEqual(resp_api.status_code, 200)
        self.assertLess(elapsed_api, 2.0, f"API query took {elapsed_api:.3f}s; expected < 2.0s")
