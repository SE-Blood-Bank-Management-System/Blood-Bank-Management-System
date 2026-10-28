"""
Automated Test Suite for Component Separation, Traceability, and Automatic Expiry.
SRS References:
- Section 4.10 (BBMS-F-031, BBMS-F-032): Component Separation Traceability
- Section 4.12 (BBMS-F-037, BBMS-F-038, BBMS-F-039): Expiry Handling & FEFO
- Section 6.1 (BBMS-SR-003): RBAC for Staff Inventory Operations
Test Plan References:
- TC-CMP-01: Component separation traceability, child Bag IDs, parent exclusion
- TC-EXP-01: Expiry calculation anchored to source collection date, automatic expiry service
"""
from datetime import timedelta
import io
import json
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from core.constants import BloodGroup
from inventory.models import (
    BloodUnit,
    BloodUnitStatus,
    ComponentType,
    REQUIRED_SEROLOGY_TESTS,
    SerologyResult,
    SerologyTest,
    SerologyTestType,
    StatusChange,
)
from inventory.services import get_inventory_counts, process_expired_units


class ComponentSeparationTraceabilityTests(TestCase):
    """
    Test suite for TC-CMP-01: Component Separation and Traceability.
    """
    def setUp(self):
        self.staff = User.objects.create_user(
            username='staff_alice',
            email='alice@bbms.local',
            role=User.Role.STAFF,
            password='Password123!'
        )
        self.admin = User.objects.create_user(
            username='admin_bob',
            email='admin@bbms.local',
            role=User.Role.ADMIN,
            password='Password123!'
        )
        self.donor = User.objects.create_user(
            username='donor_charlie',
            email='charlie@bbms.local',
            role=User.Role.DONOR,
            password='Password123!',
            blood_group='A+'
        )
        self.hospital = User.objects.create_user(
            username='hospital_metro',
            email='metro@hospital.local',
            role=User.Role.HOSPITAL,
            password='Password123!'
        )

    def _create_available_whole_blood(self, collection_date=None, blood_group='A+', location='Central Blood Bank'):
        """Helper to create a Whole Blood unit with all 4 serology tests passed."""
        c_date = collection_date or timezone.now()
        unit = BloodUnit.objects.create(
            bag_id=BloodUnit.generate_unique_bag_id(),
            donor=self.donor,
            blood_group=blood_group,
            component_type=ComponentType.WHOLE_BLOOD,
            volume_ml=450,
            collection_date=c_date,
            status=BloodUnitStatus.QUARANTINED,
            location=location,
            collected_by=self.staff,
        )
        # Record all 4 mandatory tests as Pass
        for test_type in REQUIRED_SEROLOGY_TESTS:
            SerologyTest.objects.create(
                blood_unit=unit,
                test_type=test_type,
                result=SerologyResult.PASS,
                tested_by=self.staff,
            )
        unit.status = BloodUnitStatus.AVAILABLE
        unit.expiry_date = unit.calculate_default_expiry(ComponentType.WHOLE_BLOOD, c_date)
        unit.save(actor=self.staff, status_reason='Cleared for inventory.')
        return unit

    def test_tc_cmp_01_successful_component_separation_tri_pack(self):
        """
        TC-CMP-01: Valid Whole Blood unit marked Available is separated into RBC, Platelets, and Plasma.
        Verifies:
        - Unique Bag ID generation for child components.
        - Preservation of parent_unit reference on each child.
        - Inheritance of donor, blood group, location, and collection date.
        - Inheritance of all 4 mandatory serology clearance tests.
        - Parent unit transitions to Separated status.
        - Parent unit excluded from available counts, avoiding double-counting.
        """
        parent = self._create_available_whole_blood()
        initial_counts = get_inventory_counts(location=parent.location)
        self.assertEqual(initial_counts['total_units_available'], 1)

        # Execute component separation
        children = parent.separate_into_components(staff_user=self.staff, notes="Batch separation test")
        self.assertEqual(len(children), 3)

        parent.refresh_from_db()
        self.assertEqual(parent.status, BloodUnitStatus.SEPARATED)
        self.assertTrue(parent.is_separated)
        self.assertFalse(parent.can_be_separated)

        # Verify child Bag IDs are distinct and non-empty
        child_bag_ids = [c.bag_id for c in children]
        self.assertEqual(len(set(child_bag_ids)), 3)
        self.assertNotIn(parent.bag_id, child_bag_ids)

        # Verify component types
        child_types = {c.component_type for c in children}
        expected_types = {ComponentType.RBC, ComponentType.PLATELETS, ComponentType.PLASMA}
        self.assertEqual(child_types, expected_types)

        for child in children:
            # Traceability back to originating unit (SRS BBMS-F-032)
            self.assertEqual(child.parent_unit, parent)
            self.assertEqual(child.donor, parent.donor)
            self.assertEqual(child.blood_group, parent.blood_group)
            self.assertEqual(child.location, parent.location)
            self.assertEqual(child.collection_date, parent.collection_date)
            self.assertEqual(child.status, BloodUnitStatus.AVAILABLE)

            # Serology inheritance
            self.assertTrue(child.has_passed_serology)
            serology_test_types = set(child.serology_tests.values_list('test_type', flat=True))
            self.assertEqual(serology_test_types, set(REQUIRED_SEROLOGY_TESTS))
            for st in child.serology_tests.all():
                self.assertEqual(st.result, SerologyResult.PASS)

        # Available inventory verification: Parent excluded, children included (3 total available)
        updated_counts = get_inventory_counts(location=parent.location)
        self.assertEqual(updated_counts['total_units_available'], 3)
        self.assertNotIn(parent, BloodUnit.objects.available())

    def test_tc_exp_01_child_expiry_anchored_to_source_collection_date(self):
        """
        TC-EXP-01: Expiry dates of child components must be strictly anchored to parent collection date.
        If a Whole Blood unit collected 10 days ago is separated:
        - RBC: shelf life 42 days -> expires collection_date + 42 (remaining 32 days) -> Available
        - Platelets: shelf life 5 days -> expires collection_date + 5 (in the past!) -> Expired immediately
        - Plasma: shelf life 365 days -> expires collection_date + 365 (remaining 355 days) -> Available
        """
        ten_days_ago = timezone.now() - timedelta(days=10)
        parent = self._create_available_whole_blood(collection_date=ten_days_ago)

        children = parent.separate_into_components(staff_user=self.staff)
        by_type = {c.component_type: c for c in children}

        rbc = by_type[ComponentType.RBC]
        platelets = by_type[ComponentType.PLATELETS]
        plasma = by_type[ComponentType.PLASMA]

        # Check RBC
        self.assertEqual(rbc.expiry_date, ten_days_ago + timedelta(days=42))
        self.assertEqual(rbc.status, BloodUnitStatus.AVAILABLE)

        # Check Platelets: must be expired immediately because 10 days > 5 days shelf life!
        self.assertEqual(platelets.expiry_date, ten_days_ago + timedelta(days=5))
        self.assertEqual(platelets.status, BloodUnitStatus.EXPIRED)
        self.assertTrue(platelets.is_expired)

        # Check Plasma
        self.assertEqual(plasma.expiry_date, ten_days_ago + timedelta(days=365))
        self.assertEqual(plasma.status, BloodUnitStatus.AVAILABLE)

    def test_custom_components_subset_separation(self):
        """Staff can specify producing only RBC and Plasma (omitting Platelets)."""
        parent = self._create_available_whole_blood()
        custom_specs = [
            {'component_type': ComponentType.RBC, 'volume_ml': 280},
            {'component_type': ComponentType.PLASMA, 'volume_ml': 220},
        ]
        children = parent.separate_into_components(components_data=custom_specs, staff_user=self.staff)
        self.assertEqual(len(children), 2)
        child_types = [c.component_type for c in children]
        self.assertIn(ComponentType.RBC, child_types)
        self.assertIn(ComponentType.PLASMA, child_types)
        self.assertNotIn(ComponentType.PLATELETS, child_types)

    def test_rejection_of_non_whole_blood_separation(self):
        """Attempting to separate a unit that is not Whole Blood must raise ValidationError."""
        parent = self._create_available_whole_blood()
        parent.component_type = ComponentType.RBC
        parent.save(actor=self.staff, status_reason='Testing invalid type.')

        with self.assertRaises(ValidationError) as ctx:
            parent.separate_into_components(staff_user=self.staff)
        self.assertIn("Only Whole Blood units can be separated", str(ctx.exception))

    def test_rejection_of_quarantined_unit_separation(self):
        """Attempting to separate a Quarantined unit must raise ValidationError."""
        unit = BloodUnit.objects.create(
            bag_id=BloodUnit.generate_unique_bag_id(),
            donor=self.donor,
            blood_group='O+',
            component_type=ComponentType.WHOLE_BLOOD,
            status=BloodUnitStatus.QUARANTINED,
            location='Central Blood Bank',
            collected_by=self.staff,
        )
        with self.assertRaises(ValidationError) as ctx:
            unit.separate_into_components(staff_user=self.staff)
        self.assertIn("Only Available blood units can be separated", str(ctx.exception))

    def test_rejection_of_expired_unit_separation(self):
        """Attempting to separate an expired unit must raise ValidationError."""
        past_date = timezone.now() - timedelta(days=50)
        parent = self._create_available_whole_blood(collection_date=past_date)
        # Unit is expired
        self.assertTrue(parent.is_expired)

        with self.assertRaises(ValidationError) as ctx:
            parent.separate_into_components(staff_user=self.staff)
        self.assertIn("Expired blood units cannot be separated", str(ctx.exception))

    def test_rejection_of_repeated_separation(self):
        """An already separated unit cannot be separated again."""
        parent = self._create_available_whole_blood()
        parent.separate_into_components(staff_user=self.staff)
        parent.refresh_from_db()

        with self.assertRaises(ValidationError) as ctx:
            parent.separate_into_components(staff_user=self.staff)
        self.assertIn("already been separated", str(ctx.exception))

    def test_permission_denied_for_unauthorized_users(self):
        """Donors or Hospitals calling separation domain logic must receive PermissionDenied."""
        parent = self._create_available_whole_blood()
        with self.assertRaises(PermissionDenied):
            parent.separate_into_components(staff_user=self.donor)
        with self.assertRaises(PermissionDenied):
            parent.separate_into_components(staff_user=self.hospital)

    def test_status_change_audit_history_recorded(self):
        """Status audit logs must be recorded for both parent transition and children creation."""
        parent = self._create_available_whole_blood()
        children = parent.separate_into_components(staff_user=self.staff, notes="Routine centrifuge processing")

        # Parent status history
        parent_changes = StatusChange.objects.filter(blood_unit=parent)
        self.assertTrue(parent_changes.filter(new_status=BloodUnitStatus.SEPARATED).exists())
        sep_change = parent_changes.filter(new_status=BloodUnitStatus.SEPARATED).first()
        self.assertEqual(sep_change.changed_by, self.staff)
        self.assertIn("Routine centrifuge processing", sep_change.reason)

        # Children status history
        for child in children:
            child_changes = StatusChange.objects.filter(blood_unit=child)
            self.assertTrue(child_changes.exists())


class AutomaticExpiryServiceTests(TestCase):
    """
    Test suite for TC-EXP-01: Automatic Expiry Service and Management Command.
    """
    def setUp(self):
        self.staff = User.objects.create_user(
            username='exp_staff',
            email='exp_staff@bbms.local',
            role=User.Role.STAFF,
            password='Password123!'
        )
        self.donor = User.objects.create_user(
            username='exp_donor',
            email='exp_donor@bbms.local',
            role=User.Role.DONOR,
            password='Password123!',
            blood_group='B+'
        )

    def _create_unit(self, status, expiry_date, component_type=ComponentType.WHOLE_BLOOD):
        unit = BloodUnit.objects.create(
            bag_id=BloodUnit.generate_unique_bag_id(),
            donor=self.donor,
            blood_group='B+',
            component_type=component_type,
            volume_ml=450,
            collection_date=timezone.now() - timedelta(days=50),
            status=status,
            expiry_date=expiry_date,
            location='Central Blood Bank',
        )
        return unit

    def test_process_expired_units_transitions_overdue_units_idempotently(self):
        """
        process_expired_units transitions overdue Available, Quarantined, and Allocated stock.
        Running multiple times is strictly idempotent.
        """
        now = timezone.now()
        yesterday = now - timedelta(days=1)
        tomorrow = now + timedelta(days=1)

        # Eligible overdue units
        u_avail_overdue = self._create_unit(BloodUnitStatus.AVAILABLE, yesterday)
        u_quar_overdue = self._create_unit(BloodUnitStatus.QUARANTINED, yesterday)
        u_alloc_overdue = self._create_unit(BloodUnitStatus.ALLOCATED, yesterday)

        # Non-overdue unit
        u_avail_fresh = self._create_unit(BloodUnitStatus.AVAILABLE, tomorrow)

        # Final or already expired units
        u_already_expired = self._create_unit(BloodUnitStatus.EXPIRED, yesterday)
        u_discarded = self._create_unit(BloodUnitStatus.DISCARDED, yesterday)

        # Run 1: Should process the 3 eligible overdue units
        res1 = process_expired_units(as_of=now, dry_run=False)
        self.assertEqual(res1['processed_count'], 3)
        processed_ids = [u['bag_id'] for u in res1['expired_units']]
        self.assertIn(u_avail_overdue.bag_id, processed_ids)
        self.assertIn(u_quar_overdue.bag_id, processed_ids)
        self.assertIn(u_alloc_overdue.bag_id, processed_ids)

        u_avail_overdue.refresh_from_db()
        u_quar_overdue.refresh_from_db()
        u_alloc_overdue.refresh_from_db()
        u_avail_fresh.refresh_from_db()
        u_already_expired.refresh_from_db()
        u_discarded.refresh_from_db()

        self.assertEqual(u_avail_overdue.status, BloodUnitStatus.EXPIRED)
        self.assertEqual(u_quar_overdue.status, BloodUnitStatus.EXPIRED)
        self.assertEqual(u_alloc_overdue.status, BloodUnitStatus.EXPIRED)
        self.assertEqual(u_avail_fresh.status, BloodUnitStatus.AVAILABLE)
        self.assertEqual(u_already_expired.status, BloodUnitStatus.EXPIRED)
        self.assertEqual(u_discarded.status, BloodUnitStatus.DISCARDED)

        # Run 2: Idempotency check - 0 units processed
        res2 = process_expired_units(as_of=now, dry_run=False)
        self.assertEqual(res2['processed_count'], 0)

    def test_process_expired_units_dry_run_does_not_modify_db(self):
        """dry_run=True identifies overdue units without altering their database status."""
        now = timezone.now()
        yesterday = now - timedelta(days=1)
        unit = self._create_unit(BloodUnitStatus.AVAILABLE, yesterday)

        result = process_expired_units(as_of=now, dry_run=True)
        self.assertEqual(result['processed_count'], 1)
        self.assertTrue(result['dry_run'])

        unit.refresh_from_db()
        self.assertEqual(unit.status, BloodUnitStatus.AVAILABLE)

    def test_expire_units_management_command(self):
        """Tests the `expire_units` management command with --dry-run and standard execution."""
        yesterday = timezone.now() - timedelta(days=1)
        unit = self._create_unit(BloodUnitStatus.AVAILABLE, yesterday)

        # Dry run CLI invocation
        out_dry = io.StringIO()
        call_command('expire_units', '--dry-run', stdout=out_dry)
        self.assertIn("[DRY-RUN]", out_dry.getvalue())
        self.assertIn(unit.bag_id, out_dry.getvalue())
        unit.refresh_from_db()
        self.assertEqual(unit.status, BloodUnitStatus.AVAILABLE)

        # Live execution
        out_live = io.StringIO()
        call_command('expire_units', stdout=out_live)
        self.assertIn("Successfully processed 1 blood unit", out_live.getvalue())
        unit.refresh_from_db()
        self.assertEqual(unit.status, BloodUnitStatus.EXPIRED)


class ComponentSeparationViewAndApiTests(TestCase):
    """
    Test suite for Web UI views and REST APIs for component separation and expiry.
    """
    def setUp(self):
        self.staff = User.objects.create_user(
            username='web_staff',
            email='web_staff@bbms.local',
            role=User.Role.STAFF,
            password='StaffPassword123!'
        )
        self.donor = User.objects.create_user(
            username='web_donor',
            email='web_donor@bbms.local',
            role=User.Role.DONOR,
            password='DonorPassword123!',
            blood_group='AB+'
        )
        self.hospital = User.objects.create_user(
            username='web_hospital',
            email='web_hospital@bbms.local',
            role=User.Role.HOSPITAL,
            password='HospitalPassword123!'
        )

    def _create_available_unit(self):
        unit = BloodUnit.objects.create(
            bag_id=BloodUnit.generate_unique_bag_id(),
            donor=self.donor,
            blood_group='AB+',
            component_type=ComponentType.WHOLE_BLOOD,
            volume_ml=450,
            collection_date=timezone.now(),
            status=BloodUnitStatus.AVAILABLE,
            expiry_date=timezone.now() + timedelta(days=42),
            location='Central Blood Bank',
        )
        for t in REQUIRED_SEROLOGY_TESTS:
            SerologyTest.objects.create(
                blood_unit=unit,
                test_type=t,
                result=SerologyResult.PASS,
                tested_by=self.staff,
            )
        return unit

    def test_staff_separation_ui_get_page(self):
        """Authorized staff can access the separation interface; unauthorized users are blocked."""
        unit = self._create_available_unit()

        # Staff can access
        self.client.login(username='web_staff', password='StaffPassword123!')
        url = reverse('inventory:separate_unit', kwargs={'bag_id': unit.bag_id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Component Separation")
        self.assertContains(response, unit.bag_id)

        # Donor is blocked with 403 Forbidden
        self.client.login(username='web_donor', password='DonorPassword123!')
        response_donor = self.client.get(url)
        self.assertEqual(response_donor.status_code, 403)

    def test_staff_separation_ui_post_success(self):
        """Staff submitting the HTML form successfully creates components and transitions parent."""
        unit = self._create_available_unit()
        self.client.login(username='web_staff', password='StaffPassword123!')
        url = reverse('inventory:separate_unit', kwargs={'bag_id': unit.bag_id})

        post_data = {
            'produce_rbc': 'on',
            'volume_rbc': '250',
            'produce_platelets': 'on',
            'volume_platelets': '50',
            'produce_plasma': 'on',
            'volume_plasma': '200',
            'notes': 'UI separation test',
        }
        response = self.client.post(url, post_data, follow=True)
        self.assertEqual(response.status_code, 200)

        unit.refresh_from_db()
        self.assertEqual(unit.status, BloodUnitStatus.SEPARATED)
        self.assertEqual(unit.child_components.count(), 3)

    def test_api_separate_blood_unit_success(self):
        """POST /api/blood-units/{bagId}/components/ per SAD Section 4.3 creates components and returns JSON."""
        unit = self._create_available_unit()
        self.client.login(username='web_staff', password='StaffPassword123!')
        url = f"/api/blood-units/{unit.bag_id}/components/"

        payload = {
            'components': [
                {'component_type': ComponentType.RBC, 'volume_ml': 250},
                {'component_type': ComponentType.PLASMA, 'volume_ml': 200},
            ],
            'notes': 'REST API separation test',
        }
        response = self.client.post(
            url,
            data=json.dumps(payload),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertTrue(data['success'])
        self.assertEqual(data['parent_status'], BloodUnitStatus.SEPARATED)
        self.assertEqual(len(data['components']), 2)

    def test_api_separate_blood_unit_forbidden_for_non_staff(self):
        """POST /api/blood-units/{bagId}/components/ rejects hospital or donor users with 403."""
        unit = self._create_available_unit()
        self.client.login(username='web_hospital', password='HospitalPassword123!')
        url = f"/api/blood-units/{unit.bag_id}/components/"

        response = self.client.post(url, data='{}', content_type='application/json')
        self.assertEqual(response.status_code, 403)

    def test_api_expire_units_endpoint(self):
        """POST /api/inventory/expire/ allows staff to trigger automatic expiry via REST API."""
        self.client.login(username='web_staff', password='StaffPassword123!')
        url = "/api/inventory/expire/"

        response = self.client.post(
            url,
            data=json.dumps({'dry_run': True}),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        self.assertTrue(data['dry_run'])
