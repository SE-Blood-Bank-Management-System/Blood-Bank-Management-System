"""
Comprehensive unit and integration tests for FEFO Allocation, Dispatch Manifests,
and Requisition Fulfilment (Issue #37).

SRS References:
- Section 4.11 (BBMS-F-035): Inventory decrement on allocation
- Section 4.12 (BBMS-F-038, BBMS-F-039): First-Expiry-First-Out (FEFO) ordering & Expiry exclusion
- Section 4.16 (BBMS-F-049, BBMS-F-050, BBMS-F-051): ABO/Rh Compatibility, Override & Cross-matching
- Section 4.17 (BBMS-F-052, BBMS-F-053, BBMS-F-054, BBMS-F-055): Allocation, Dispatch Manifests & Fulfilment

Test Plan Cases:
- TC-INV-01: Inventory counts, location grouping, and FEFO expiry ordering
- TC-INV-02: Inventory availability count updates after allocation/dispatch
- TC-EXP-01: Expiry handling and exclusion of expired stock
- TC-MATCH-01: Transfusion compatibility rules and clinical override justification
- TC-DISP-01: Allocation by Bag ID, dispatch manifest creation, status transitions, and fulfilment
"""
import json
from datetime import timedelta
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from core.constants import BloodGroup
from inventory.models import (
    Allocation,
    AllocationStatus,
    BloodUnit,
    BloodUnitStatus,
    ComponentType,
    CrossMatchOutcome,
    DispatchManifest,
    REQUIRED_SEROLOGY_TESTS,
    SerologyResult,
    SerologyTest,
    StatusChange,
)
from inventory.services import (
    AllocationConflict,
    allocate_units_to_requisition,
    cancel_reservation,
    dispatch_allocated_units,
    get_available_units_for_requisition,
    get_fefo_allocation_suggestions,
    get_inventory_counts,
)
from requisitions.models import Requisition, RequisitionEvent, RequisitionFulfilment
from requisitions.services import review_requisition, submit_requisition


class FEFOAllocationDispatchTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        # 1. Accounts
        cls.staff = User.objects.create_user(
            username='staff_allocator',
            email='staff.allocator@bbms.local',
            password='StaffPassword@123',
            role=User.Role.STAFF,
            first_name='Alice',
            last_name='Staff'
        )
        cls.hospital_user = User.objects.create_user(
            username='hospital_apollo',
            email='apollo@hospital.local',
            password='HospitalPassword@123',
            role=User.Role.HOSPITAL,
            hospital_name='Apollo General Hospital',
            is_approved=True
        )
        cls.other_hospital = User.objects.create_user(
            username='hospital_fortis',
            email='fortis@hospital.local',
            password='HospitalPassword@123',
            role=User.Role.HOSPITAL,
            hospital_name='Fortis Hospital',
            is_approved=True
        )
        cls.donor = User.objects.create_user(
            username='donor_test',
            email='donor@bbms.local',
            password='DonorPassword@123',
            role=User.Role.DONOR,
            first_name='Bob',
            last_name='Donor'
        )

    def setUp(self):
        self.client = Client()

    def create_blood_unit(self, blood_group='O+', component_type=ComponentType.RBC,
                          days_to_expiry=10, collection_offset_days=5, status=BloodUnitStatus.AVAILABLE,
                          passed_serology=True, location='Central Blood Bank'):
        """Helper to create a unit with passed serology and specified expiry."""
        now = timezone.now()
        unit = BloodUnit.objects.create(
            donor=self.donor,
            blood_group=blood_group,
            component_type=component_type,
            volume_ml=450,
            collection_date=now - timedelta(days=collection_offset_days),
            expiry_date=now + timedelta(days=days_to_expiry),
            status=status,
            location=location,
        )
        if passed_serology:
            for test_type in REQUIRED_SEROLOGY_TESTS:
                SerologyTest.objects.create(
                    blood_unit=unit,
                    test_type=test_type,
                    result=SerologyResult.PASS,
                    tested_by=self.staff
                )
        return unit

    def create_approved_requisition(self, blood_group='A+', component_type=ComponentType.RBC,
                                    quantity=2, is_stat=False):
        """Helper to create an approved requisition."""
        req = submit_requisition(
            actor=self.hospital_user,
            blood_group=blood_group,
            component_type=component_type,
            quantity=quantity,
            required_by=timezone.localdate() + timedelta(days=1),
            is_stat=is_stat
        )
        reviewed = review_requisition(req.pk, actor=self.staff, action='approve')
        return reviewed

    # ==========================================================================
    # TC-INV-01: FEFO Ordering & Deterministic Tie-Breaking
    # ==========================================================================
    def test_tc_inv_01_fefo_suggestion_ordering(self):
        """
        Verify that suggestions return compatible safe unexpired units
        strictly in First-Expiry-First-Out (FEFO) order with deterministic tie breaking.
        """
        req = self.create_approved_requisition(blood_group='A+', quantity=3)

        # Create 3 compatible units with different expiry dates:
        # Unit 1 expires in 15 days
        u1 = self.create_blood_unit(blood_group='A+', days_to_expiry=15, collection_offset_days=10)
        # Unit 2 expires in 3 days (should be 1st)
        u2 = self.create_blood_unit(blood_group='O+', days_to_expiry=3, collection_offset_days=20)
        # Unit 3 expires in 7 days (should be 2nd)
        u3 = self.create_blood_unit(blood_group='A-', days_to_expiry=7, collection_offset_days=15)
        # Unit 4 is expired (should be excluded)
        u4 = self.create_blood_unit(blood_group='A+', days_to_expiry=-1, status=BloodUnitStatus.EXPIRED)
        # Unit 5 is incompatible B+ (should be excluded from compatible suggestions)
        u5 = self.create_blood_unit(blood_group='B+', days_to_expiry=2)

        suggestions = get_fefo_allocation_suggestions(req)

        self.assertEqual(len(suggestions), 3)
        self.assertEqual(suggestions[0].pk, u2.pk)  # expires in 3 days
        self.assertEqual(suggestions[1].pk, u3.pk)  # expires in 7 days
        self.assertEqual(suggestions[2].pk, u1.pk)  # expires in 15 days
        self.assertNotIn(u4.pk, [s.pk for s in suggestions])
        self.assertNotIn(u5.pk, [s.pk for s in suggestions])

    def test_tc_inv_01_fefo_deterministic_tie_breaking(self):
        """
        Verify tie-breaking on collection_date and bag_id when expiry dates are identical.
        """
        req = self.create_approved_requisition(blood_group='O+', quantity=2)

        # Two units with identical expiry, but different collection dates
        u_older = self.create_blood_unit(blood_group='O+', days_to_expiry=10, collection_offset_days=8)
        u_newer = self.create_blood_unit(blood_group='O+', days_to_expiry=10, collection_offset_days=2)

        suggestions = get_fefo_allocation_suggestions(req)
        self.assertEqual(suggestions[0].pk, u_older.pk)
        self.assertEqual(suggestions[1].pk, u_newer.pk)

    # ==========================================================================
    # TC-INV-02: Inventory Count Reconciliation (No Double-Decrement)
    # ==========================================================================
    def test_tc_inv_02_count_decrement_on_allocation_and_dispatch(self):
        """
        Verify inventory available count decrements when a unit is Allocated (BBMS-F-035)
        and is NOT decremented a second time when Dispatched (BBMS-F-054).
        """
        unit = self.create_blood_unit(blood_group='B+')
        req = self.create_approved_requisition(blood_group='B+', quantity=1)

        # Baseline count
        baseline = get_inventory_counts()['total_units_available']
        self.assertGreaterEqual(baseline, 1)

        # 1. Allocate unit -> count must decrement by 1
        allocations = allocate_units_to_requisition(
            requisition_pk=req.pk,
            unit_ids=[unit.pk],
            actor=self.staff
        )
        self.assertEqual(len(allocations), 1)
        after_alloc_counts = get_inventory_counts()['total_units_available']
        self.assertEqual(after_alloc_counts, baseline - 1)

        # Unit status is now Allocated
        unit.refresh_from_db()
        self.assertEqual(unit.status, BloodUnitStatus.ALLOCATED)

        # 2. Dispatch unit -> count must NOT decrement again
        manifest, updated_req = dispatch_allocated_units(
            requisition_pk=req.pk,
            unit_ids=[unit.pk],
            actor=self.staff
        )
        after_dispatch_counts = get_inventory_counts()['total_units_available']
        self.assertEqual(after_dispatch_counts, baseline - 1)

        unit.refresh_from_db()
        self.assertEqual(unit.status, BloodUnitStatus.DISPATCHED)

    def test_tc_inv_02_count_restoration_on_reservation_cancellation(self):
        """
        Verify that cancelling an active reservation restores the unit to Available
        and increments the available count (unless the unit has expired).
        """
        unit = self.create_blood_unit(blood_group='AB+', days_to_expiry=10)
        req = self.create_approved_requisition(blood_group='AB+', quantity=1)

        baseline = get_inventory_counts()['total_units_available']

        allocations = allocate_units_to_requisition(
            requisition_pk=req.pk,
            unit_ids=[unit.pk],
            actor=self.staff
        )
        self.assertEqual(get_inventory_counts()['total_units_available'], baseline - 1)

        # Cancel reservation
        cancel_reservation(allocations[0].pk, actor=self.staff, reason="Hospital changed order")
        self.assertEqual(get_inventory_counts()['total_units_available'], baseline)

        unit.refresh_from_db()
        self.assertEqual(unit.status, BloodUnitStatus.AVAILABLE)

    # ==========================================================================
    # TC-EXP-01: Expiry Handling & Blocking
    # ==========================================================================
    def test_tc_exp_01_expired_units_blocked_from_allocation(self):
        """
        Verify that expired units cannot be allocated (BBMS-F-039).
        """
        req = self.create_approved_requisition(blood_group='O+', quantity=1)
        expired_unit = self.create_blood_unit(blood_group='O+', days_to_expiry=-2)

        with self.assertRaises(ValidationError) as ctx:
            allocate_units_to_requisition(
                requisition_pk=req.pk,
                unit_ids=[expired_unit.pk],
                actor=self.staff
            )
        self.assertIn('expired', str(ctx.exception).lower())

    def test_tc_exp_01_unit_expiring_after_allocation_blocked_at_dispatch(self):
        """
        Verify safety recheck: if an allocated unit expires before dispatch,
        dispatch execution must reject the unit (BBMS-F-039, BBMS-F-054).
        """
        req = self.create_approved_requisition(blood_group='O+', quantity=1)
        # Unit valid at allocation time (+1 day)
        unit = self.create_blood_unit(blood_group='O+', days_to_expiry=1)

        allocate_units_to_requisition(
            requisition_pk=req.pk,
            unit_ids=[unit.pk],
            actor=self.staff
        )

        # Simulate time advancement past expiry date
        unit.expiry_date = timezone.now() - timedelta(hours=1)
        unit.save(update_fields=['expiry_date'])

        with self.assertRaises(ValidationError) as ctx:
            dispatch_allocated_units(
                requisition_pk=req.pk,
                unit_ids=[unit.pk],
                actor=self.staff
            )
        self.assertIn('expired', str(ctx.exception).lower())

    # ==========================================================================
    # TC-MATCH-01: Compatibility Rules & Clinical Override
    # ==========================================================================
    def test_tc_match_01_compatible_allocation_recorded(self):
        """
        Verify that compatible unit allocations are recorded with outcome 'Compatible'.
        """
        # A+ recipient can accept A+ or O-
        req = self.create_approved_requisition(blood_group='A+', quantity=1)
        unit = self.create_blood_unit(blood_group='O-')

        allocations = allocate_units_to_requisition(
            requisition_pk=req.pk,
            unit_ids=[unit.pk],
            actor=self.staff
        )
        self.assertEqual(len(allocations), 1)
        self.assertEqual(allocations[0].cross_match_outcome, CrossMatchOutcome.COMPATIBLE)
        self.assertEqual(allocations[0].override_reason, '')

    def test_tc_match_01_incompatible_allocation_blocked_without_override(self):
        """
        Verify that allocating an incompatible blood unit without justification
        is rejected (BBMS-F-050).
        """
        # O+ recipient CANNOT accept B+
        req = self.create_approved_requisition(blood_group='O+', quantity=1)
        unit = self.create_blood_unit(blood_group='B+')

        with self.assertRaises(ValidationError) as ctx:
            allocate_units_to_requisition(
                requisition_pk=req.pk,
                unit_ids=[unit.pk],
                actor=self.staff,
                override_reason=''  # Empty override justification
            )
        self.assertIn('override justification is required', str(ctx.exception).lower())

    def test_tc_match_01_incompatible_allocation_permitted_with_override(self):
        """
        Verify that allocating an incompatible unit is permitted when authorized staff
        provides explicit clinical justification (BBMS-F-050, BBMS-F-051).
        """
        req = self.create_approved_requisition(blood_group='O+', quantity=1)
        unit = self.create_blood_unit(blood_group='B+')

        justification = "Emergency STAT life-threatening trauma exception approved by Dr. Sharma."
        allocations = allocate_units_to_requisition(
            requisition_pk=req.pk,
            unit_ids=[unit.pk],
            actor=self.staff,
            override_reason=justification
        )
        self.assertEqual(len(allocations), 1)
        self.assertEqual(allocations[0].cross_match_outcome, CrossMatchOutcome.OVERRIDDEN)
        self.assertEqual(allocations[0].override_reason, justification)

    # ==========================================================================
    # TC-DISP-01: Dispatch Manifest Creation & Cumulative Fulfilment
    # ==========================================================================
    def test_tc_disp_01_partial_and_full_dispatch_fulfilment(self):
        """
        Verify multi-step dispatch:
        Step 1: Dispatch 1 unit -> status 'Partially Fulfilled', remaining 1.
        Step 2: Dispatch 2nd unit -> status 'Fulfilled', remaining 0.
        Verify DispatchManifest contents (requisition, bag IDs, staff, timestamp).
        """
        req = self.create_approved_requisition(blood_group='O+', quantity=2)
        u1 = self.create_blood_unit(blood_group='O+')
        u2 = self.create_blood_unit(blood_group='O+')

        # Allocate both units
        allocate_units_to_requisition(requisition_pk=req.pk, unit_ids=[u1.pk, u2.pk], actor=self.staff)
        req.refresh_from_db()
        self.assertEqual(req.status, Requisition.Status.APPROVED)

        # Dispatch 1st unit
        manifest1, updated_req = dispatch_allocated_units(
            requisition_pk=req.pk,
            unit_ids=[u1.pk],
            actor=self.staff,
            notes="First parcel dispatched via FastCourier vehicle BB-01."
        )

        self.assertEqual(updated_req.status, Requisition.Status.PARTIALLY_FULFILLED)
        self.assertEqual(updated_req.dispatched_quantity, 1)
        self.assertEqual(updated_req.remaining_quantity, 1)
        self.assertTrue(manifest1.manifest_id.startswith('MAN-'))
        self.assertEqual(manifest1.unit_count, 1)
        self.assertIn(u1.bag_id, manifest1.bag_ids)
        self.assertEqual(manifest1.dispatched_by, self.staff)

        # Dispatch 2nd unit
        manifest2, updated_req2 = dispatch_allocated_units(
            requisition_pk=req.pk,
            unit_ids=[u2.pk],
            actor=self.staff,
            notes="Second parcel completed."
        )

        self.assertEqual(updated_req2.status, Requisition.Status.FULFILLED)
        self.assertEqual(updated_req2.dispatched_quantity, 2)
        self.assertEqual(updated_req2.remaining_quantity, 0)
        self.assertEqual(manifest2.unit_count, 1)
        self.assertIn(u2.bag_id, manifest2.bag_ids)

        # Verify audit trails
        self.assertEqual(RequisitionFulfilment.objects.filter(requisition=req).count(), 2)
        event = RequisitionEvent.objects.filter(
            requisition=req, action=RequisitionEvent.Action.DISPATCH_RECORDED, new_status='Fulfilled'
        ).first()
        self.assertIsNotNone(event)
        self.assertIn(u2.bag_id, event.note)

    # ==========================================================================
    # Concurrency, Integrity & Safeguard Tests
    # ==========================================================================
    def test_duplicate_reservation_prevented(self):
        """
        Verify that the same blood unit cannot be reserved for two different requisitions.
        """
        req1 = self.create_approved_requisition(blood_group='O+', quantity=1)
        req2 = self.create_approved_requisition(blood_group='O+', quantity=1)
        unit = self.create_blood_unit(blood_group='O+')

        # Reserve for req1
        allocate_units_to_requisition(requisition_pk=req1.pk, unit_ids=[unit.pk], actor=self.staff)

        # Attempt to reserve for req2
        with self.assertRaises((ValidationError, AllocationConflict)):
            allocate_units_to_requisition(requisition_pk=req2.pk, unit_ids=[unit.pk], actor=self.staff)

    def test_over_allocation_prevented(self):
        """
        Verify that staff cannot reserve more units than the requisition requires.
        """
        req = self.create_approved_requisition(blood_group='O+', quantity=1)
        u1 = self.create_blood_unit(blood_group='O+')
        u2 = self.create_blood_unit(blood_group='O+')

        with self.assertRaises(ValidationError) as ctx:
            allocate_units_to_requisition(
                requisition_pk=req.pk,
                unit_ids=[u1.pk, u2.pk],
                actor=self.staff
            )
        self.assertIn('only 1 remaining units can be reserved', str(ctx.exception).lower())

    def test_untested_serology_unit_blocked(self):
        """
        Verify that a unit with missing or incomplete serology cannot be allocated.
        """
        req = self.create_approved_requisition(blood_group='O+', quantity=1)
        untested_unit = self.create_blood_unit(blood_group='O+', passed_serology=False)

        with self.assertRaises(ValidationError) as ctx:
            allocate_units_to_requisition(
                requisition_pk=req.pk,
                unit_ids=[untested_unit.pk],
                actor=self.staff
            )
        self.assertIn('serology', str(ctx.exception).lower())

    def test_dispatch_unreserved_unit_blocked(self):
        """
        Verify that dispatching a unit that has not been reserved for this requisition is blocked.
        """
        req = self.create_approved_requisition(blood_group='O+', quantity=1)
        unreserved_unit = self.create_blood_unit(blood_group='O+')

        with self.assertRaises(ValidationError):
            dispatch_allocated_units(
                requisition_pk=req.pk,
                unit_ids=[unreserved_unit.pk],
                actor=self.staff
            )

    def test_non_staff_permission_denied(self):
        """
        Verify that hospital users and unauthenticated users cannot allocate or dispatch units.
        """
        req = self.create_approved_requisition(blood_group='O+', quantity=1)
        unit = self.create_blood_unit(blood_group='O+')

        # Hospital actor
        with self.assertRaises(PermissionDenied):
            allocate_units_to_requisition(
                requisition_pk=req.pk,
                unit_ids=[unit.pk],
                actor=self.hospital_user
            )

        with self.assertRaises(PermissionDenied):
            dispatch_allocated_units(
                requisition_pk=req.pk,
                unit_ids=[unit.pk],
                actor=self.hospital_user
            )

    # ==========================================================================
    # HTML Views & REST API Endpoints Integration Tests
    # ==========================================================================
    def test_allocate_and_dispatch_html_views(self):
        """
        Test GET and POST flows on HTML allocation and dispatch views.
        """
        req = self.create_approved_requisition(blood_group='O+', quantity=1)
        unit = self.create_blood_unit(blood_group='O+')

        self.client.force_login(self.staff)

        # GET allocate view
        resp = self.client.get(reverse('inventory:allocate_requisition', kwargs={'requisition_pk': req.pk}))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, req.requisition_id)
        self.assertContains(resp, unit.bag_id)

        # POST allocate view
        post_resp = self.client.post(
            reverse('inventory:allocate_requisition', kwargs={'requisition_pk': req.pk}),
            {'unit_ids': str(unit.pk), 'override_reason': ''}
        )
        self.assertEqual(post_resp.status_code, 302)

        # GET dispatch view
        disp_resp = self.client.get(reverse('inventory:dispatch_requisition', kwargs={'requisition_pk': req.pk}))
        self.assertEqual(disp_resp.status_code, 200)
        self.assertContains(disp_resp, unit.bag_id)

        # POST dispatch view
        post_disp_resp = self.client.post(
            reverse('inventory:dispatch_requisition', kwargs={'requisition_pk': req.pk}),
            {'unit_ids': str(unit.pk), 'notes': 'Test courier'}
        )
        self.assertEqual(post_disp_resp.status_code, 302)

        manifest = DispatchManifest.objects.filter(requisition=req).first()
        self.assertIsNotNone(manifest)

        # GET manifest detail view
        man_resp = self.client.get(reverse('inventory:manifest_detail', kwargs={'manifest_id': manifest.manifest_id}))
        self.assertEqual(man_resp.status_code, 200)
        self.assertContains(man_resp, manifest.manifest_id)
        self.assertContains(man_resp, unit.bag_id)

    def test_rest_api_fefo_suggestions_and_allocation(self):
        """
        Test JSON REST API endpoints for suggestions, allocation, and dispatch.
        """
        req = self.create_approved_requisition(blood_group='B+', quantity=1)
        unit = self.create_blood_unit(blood_group='B+')

        self.client.force_login(self.staff)

        # GET suggestions API
        resp = self.client.get(reverse('inventory:api_fefo_suggestions', kwargs={'requisition_pk': req.pk}))
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(len(data['suggested_units']), 1)
        self.assertEqual(data['suggested_units'][0]['bag_id'], unit.bag_id)

        # POST allocate API
        alloc_resp = self.client.post(
            reverse('inventory:api_allocate_units', kwargs={'requisition_pk': req.pk}),
            data=json.dumps({'unit_ids': [unit.pk]}),
            content_type='application/json'
        )
        self.assertEqual(alloc_resp.status_code, 201)
        alloc_data = alloc_resp.json()
        self.assertEqual(alloc_data['allocated_count'], 1)

        # POST dispatch API
        disp_resp = self.client.post(
            reverse('inventory:api_dispatch_units', kwargs={'requisition_pk': req.pk}),
            data=json.dumps({'unit_ids': [unit.pk], 'notes': 'Courier XYZ'}),
            content_type='application/json'
        )
        self.assertEqual(disp_resp.status_code, 200)
        disp_data = disp_resp.json()
        self.assertEqual(disp_data['requisition_status'], 'Fulfilled')
        self.assertEqual(disp_data['remaining_quantity'], 0)

        # GET manifest API
        man_id = disp_data['manifest_id']
        man_resp = self.client.get(reverse('inventory:api_manifest_detail', kwargs={'manifest_id': man_id}))
        self.assertEqual(man_resp.status_code, 200)
        man_data = man_resp.json()
        self.assertEqual(man_data['manifest_id'], man_id)
        self.assertEqual(len(man_data['units']), 1)
        self.assertEqual(man_data['units'][0]['bag_id'], unit.bag_id)

    def test_hospital_manifest_access_isolation(self):
        """
        Verify that a hospital can view manifests for its own requisitions,
        but gets 403 Forbidden when attempting to view another hospital's manifest.
        """
        req = self.create_approved_requisition(blood_group='O+', quantity=1)
        unit = self.create_blood_unit(blood_group='O+')

        allocate_units_to_requisition(requisition_pk=req.pk, unit_ids=[unit.pk], actor=self.staff)
        manifest, _ = dispatch_allocated_units(requisition_pk=req.pk, unit_ids=[unit.pk], actor=self.staff)

        # Owning hospital can access
        self.client.force_login(self.hospital_user)
        own_resp = self.client.get(reverse('inventory:manifest_detail', kwargs={'manifest_id': manifest.manifest_id}))
        self.assertEqual(own_resp.status_code, 200)

        # Other hospital cannot access (raises PermissionDenied)
        self.client.force_login(self.other_hospital)
        other_resp = self.client.get(reverse('inventory:manifest_detail', kwargs={'manifest_id': manifest.manifest_id}))
        self.assertEqual(other_resp.status_code, 403)
