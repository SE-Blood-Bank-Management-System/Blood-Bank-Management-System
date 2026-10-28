"""
Automated Test Suite for Compatibility Cross-Matching and Staff Overrides.
SRS References:
- Section 4.16 (BBMS-F-049 to BBMS-F-051): Blood Compatibility and Cross-Matching
- Section 6.1 (BBMS-SR-003, BBMS-SR-004, BBMS-SR-008): Security & Auditability
Test Plan References:
- TC-MATCH-01: ABO/Rh compatibility and allocation restriction
- TC-SEC-03: Role-based authorization enforcement
- TC-SEC-08: Protected clinical operation auditing
"""
from datetime import timedelta
import json
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from core.constants import BloodGroup, RBC_COMPATIBILITY_RULES
from inventory.models import (
    BloodUnit,
    BloodUnitStatus,
    ComponentType,
    REQUIRED_SEROLOGY_TESTS,
    SerologyResult,
    SerologyTest,
)
from requisitions.compatibility import (
    explain_compatibility,
    get_compatible_donor_groups,
    is_transfusion_compatible,
)
from requisitions.models import (
    CrossMatchDecision,
    CrossMatchOutcome,
    Requisition,
    RequisitionEvent,
)
from requisitions.services import (
    evaluate_unit_for_requisition,
    get_compatible_inventory_for_requisition,
    record_cross_match,
    review_requisition,
    submit_requisition,
)


class CompatibilityPolicyTests(TestCase):
    """
    Unit tests for transfusion compatibility policy logic across components (SRS BBMS-F-049).
    """
    def test_rbc_compatibility_matrix_all_eight_groups(self):
        """Validates standard erythrocyte compatibility across all 8 ABO/Rh groups."""
        # O- is universal RBC donor
        for recipient in BloodGroup.values:
            self.assertTrue(
                is_transfusion_compatible(BloodGroup.O_NEG, recipient, ComponentType.RBC),
                f"O- must be compatible with {recipient}"
            )

        # AB+ is universal RBC recipient
        for donor in BloodGroup.values:
            self.assertTrue(
                is_transfusion_compatible(donor, BloodGroup.AB_POS, ComponentType.RBC),
                f"{donor} must be compatible with AB+"
            )

        # O- recipient can only receive O-
        self.assertEqual(get_compatible_donor_groups(BloodGroup.O_NEG, ComponentType.RBC), (BloodGroup.O_NEG,))
        self.assertFalse(is_transfusion_compatible(BloodGroup.O_POS, BloodGroup.O_NEG, ComponentType.RBC))
        self.assertFalse(is_transfusion_compatible(BloodGroup.A_POS, BloodGroup.O_NEG, ComponentType.RBC))

        # A+ recipient can receive O-, O+, A-, A+
        expected_a_pos = (BloodGroup.O_NEG, BloodGroup.O_POS, BloodGroup.A_NEG, BloodGroup.A_POS)
        self.assertEqual(get_compatible_donor_groups(BloodGroup.A_POS, ComponentType.RBC), expected_a_pos)
        self.assertTrue(is_transfusion_compatible(BloodGroup.A_NEG, BloodGroup.A_POS, ComponentType.RBC))
        self.assertFalse(is_transfusion_compatible(BloodGroup.B_POS, BloodGroup.A_POS, ComponentType.RBC))

    def test_plasma_compatibility_inverse_antibody_rules(self):
        """
        Validates plasma compatibility: AB is universal plasma donor;
        O recipient can receive plasma from all ABO groups.
        """
        # AB plasma has no Anti-A or Anti-B: universal plasma donor
        for recipient in BloodGroup.values:
            self.assertTrue(
                is_transfusion_compatible(BloodGroup.AB_POS, recipient, ComponentType.PLASMA),
                f"AB+ plasma must be compatible with {recipient}"
            )
            self.assertTrue(
                is_transfusion_compatible(BloodGroup.AB_NEG, recipient, ComponentType.PLASMA),
                f"AB- plasma must be compatible with {recipient}"
            )

        # Recipient O has no A or B antigens on RBCs: can receive plasma from O, A, B, AB
        for donor in BloodGroup.values:
            self.assertTrue(
                is_transfusion_compatible(donor, BloodGroup.O_POS, ComponentType.PLASMA),
                f"Donor {donor} plasma must be compatible with O+ recipient"
            )

        # Recipient AB: can only receive AB plasma (recipient RBCs have both A and B antigens)
        self.assertFalse(is_transfusion_compatible(BloodGroup.O_POS, BloodGroup.AB_POS, ComponentType.PLASMA))
        self.assertFalse(is_transfusion_compatible(BloodGroup.A_POS, BloodGroup.AB_POS, ComponentType.PLASMA))
        self.assertFalse(is_transfusion_compatible(BloodGroup.B_POS, BloodGroup.AB_POS, ComponentType.PLASMA))
        self.assertTrue(is_transfusion_compatible(BloodGroup.AB_POS, BloodGroup.AB_POS, ComponentType.PLASMA))

    def test_explain_compatibility_provides_clinical_rationale(self):
        """explain_compatibility returns clinically sound rationale for matched and mismatched blood."""
        exp_match = explain_compatibility('O-', 'A+', ComponentType.RBC)
        self.assertIn("Universal donor RBC match", exp_match)

        exp_mismatch = explain_compatibility('B+', 'A+', ComponentType.RBC)
        self.assertIn("incompatible", exp_mismatch.lower())
        self.assertIn("hemolyze", exp_mismatch.lower())

        exp_plasma = explain_compatibility('AB+', 'O+', ComponentType.PLASMA)
        self.assertIn("Universal plasma donor", exp_plasma)


class CrossMatchingServiceTests(TestCase):
    """
    Test suite for TC-MATCH-01 service logic and staff overrides (SRS BBMS-F-049 to BBMS-F-051).
    """
    def setUp(self):
        self.hospital = User.objects.create_user(
            username='hosp_general',
            email='hosp@general.local',
            role=User.Role.HOSPITAL,
            hospital_name='General Hospital'
        )
        self.staff = User.objects.create_user(
            username='staff_kevin',
            email='kevin@bbms.local',
            role=User.Role.STAFF
        )
        self.donor = User.objects.create_user(
            username='donor_dan',
            email='dan@bbms.local',
            role=User.Role.DONOR,
            blood_group='A+'
        )

        # Create and approve a requisition for A+ Red Blood Cells
        self.req_a_pos = submit_requisition(
            actor=self.hospital,
            blood_group='A+',
            component_type=ComponentType.RBC,
            quantity=2,
            required_by=timezone.localdate() + timedelta(days=2),
        )
        review_requisition(self.req_a_pos.pk, actor=self.staff, action='approve')
        self.req_a_pos.refresh_from_db()

    def _create_available_unit(self, blood_group, component_type=ComponentType.RBC):
        unit = BloodUnit.objects.create(
            bag_id=BloodUnit.generate_unique_bag_id(),
            donor=self.donor,
            blood_group=blood_group,
            component_type=component_type,
            volume_ml=250,
            collection_date=timezone.now() - timedelta(days=2),
            status=BloodUnitStatus.AVAILABLE,
            expiry_date=timezone.now() + timedelta(days=40),
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

    def test_tc_match_01_compatible_cross_match_accepted(self):
        """
        TC-MATCH-01 Step 1 & 2: A compatible unit (O- or A+) is accepted without requiring override.
        Outcome recorded as 'Compatible'.
        """
        unit_o_neg = self._create_available_unit(blood_group='O-')
        decision = record_cross_match(
            self.req_a_pos.pk,
            unit_o_neg.bag_id,
            actor=self.staff,
        )

        self.assertEqual(decision.outcome, CrossMatchOutcome.COMPATIBLE)
        self.assertTrue(decision.is_compatible)
        self.assertFalse(decision.is_overridden)
        self.assertEqual(decision.performed_by, self.staff)
        self.assertEqual(decision.requested_blood_group, 'A+')
        self.assertEqual(decision.donor_blood_group, 'O-')

        # Check append-only event recorded on requisition
        event = self.req_a_pos.events.filter(action=RequisitionEvent.Action.CROSS_MATCH_RECORDED).last()
        self.assertIsNotNone(event)
        self.assertIn('Compatible', event.note)

    def test_tc_match_01_incompatible_cross_match_blocked_without_override(self):
        """
        TC-MATCH-01 Step 3: An incompatible unit (B+ for A+ requisition) is strictly
        blocked when no override rationale is supplied (SRS BBMS-F-050).
        """
        unit_b_pos = self._create_available_unit(blood_group='B+')

        with self.assertRaises(ValidationError) as ctx:
            record_cross_match(
                self.req_a_pos.pk,
                unit_b_pos.bag_id,
                actor=self.staff,
                override_reason='',
            )
        self.assertIn("INCOMPATIBLE", str(ctx.exception))
        self.assertIn("override justification", str(ctx.exception))
        self.assertFalse(CrossMatchDecision.objects.filter(blood_unit=unit_b_pos).exists())

    def test_tc_match_01_incompatible_cross_match_allowed_with_authorized_override(self):
        """
        TC-MATCH-01 Step 4: When authorized staff supplies explicit clinical justification,
        incompatible cross-match is recorded with outcome 'Overridden' (SRS BBMS-F-050, BBMS-F-051).
        """
        unit_b_pos = self._create_available_unit(blood_group='B+')
        override_text = "Emergency extreme shortage protocol authorized by Chief Medical Officer Dr. Evans."

        decision = record_cross_match(
            self.req_a_pos.pk,
            unit_b_pos.bag_id,
            actor=self.staff,
            override_reason=override_text,
        )

        self.assertEqual(decision.outcome, CrossMatchOutcome.OVERRIDDEN)
        self.assertFalse(decision.is_compatible)
        self.assertTrue(decision.is_overridden)
        self.assertEqual(decision.override_reason, override_text)
        self.assertEqual(decision.performed_by, self.staff)

        # Audit event recorded
        event = self.req_a_pos.events.filter(action=RequisitionEvent.Action.CROSS_MATCH_RECORDED).last()
        self.assertIn('Overridden', event.note)
        self.assertIn(override_text, event.note)

    def test_override_never_bypasses_expired_safety(self):
        """Expired units are strictly blocked even if an override rationale is provided (SRS BBMS-F-039)."""
        unit_expired = self._create_available_unit(blood_group='A+')
        unit_expired.expiry_date = timezone.now() - timedelta(days=1)
        unit_expired.save(actor=self.staff, status_reason='Test expired.')

        with self.assertRaises(ValidationError) as ctx:
            record_cross_match(
                self.req_a_pos.pk,
                unit_expired.bag_id,
                actor=self.staff,
                override_reason="Attempting to override expired stock",
            )
        self.assertIn("expired", str(ctx.exception).lower())

    def test_override_never_bypasses_serology_safety(self):
        """Units with incomplete or failed serology cannot be cross-matched or allocated (SRS BBMS-F-024)."""
        unit_quar = BloodUnit.objects.create(
            bag_id=BloodUnit.generate_unique_bag_id(),
            donor=self.donor,
            blood_group='A+',
            component_type=ComponentType.RBC,
            status=BloodUnitStatus.QUARANTINED,
            location='Central Blood Bank',
        )
        with self.assertRaises(ValidationError) as ctx:
            record_cross_match(
                self.req_a_pos.pk,
                unit_quar.bag_id,
                actor=self.staff,
                override_reason="Attempting to override quarantined unit",
            )
        self.assertIn("not available", str(ctx.exception).lower())

    def test_override_never_bypasses_component_mismatch(self):
        """Units with mismatched component types cannot be cross-matched."""
        unit_plasma = self._create_available_unit(blood_group='A+', component_type=ComponentType.PLASMA)
        with self.assertRaises(ValidationError) as ctx:
            record_cross_match(
                self.req_a_pos.pk,
                unit_plasma.bag_id,
                actor=self.staff,
                override_reason="Attempting to cross-match plasma for RBC requisition",
            )
        self.assertIn("Component mismatch", str(ctx.exception))

    def test_cross_match_blocked_on_unapproved_requisition(self):
        """Cross-matching can only be performed on Approved or Partially Fulfilled requisitions."""
        req_pending = submit_requisition(
            actor=self.hospital,
            blood_group='B+',
            component_type=ComponentType.RBC,
            quantity=1,
            required_by=timezone.localdate() + timedelta(days=2),
        )
        unit = self._create_available_unit(blood_group='B+')
        with self.assertRaises(ValidationError) as ctx:
            record_cross_match(req_pending.pk, unit.bag_id, actor=self.staff)
        self.assertIn("approved", str(ctx.exception).lower())

    def test_fefo_compatible_inventory_lookup(self):
        """get_compatible_inventory_for_requisition returns units in FEFO order."""
        now = timezone.now()
        # Older expiry unit
        unit_older = self._create_available_unit('O-')
        unit_older.expiry_date = now + timedelta(days=5)
        unit_older.save(actor=self.staff, status_reason='Set older expiry.')

        # Newer expiry unit
        unit_newer = self._create_available_unit('A+')
        unit_newer.expiry_date = now + timedelta(days=20)
        unit_newer.save(actor=self.staff, status_reason='Set newer expiry.')

        # Incompatible unit
        unit_incompat = self._create_available_unit('B+')

        fefo_stock = list(get_compatible_inventory_for_requisition(self.req_a_pos))
        self.assertIn(unit_older, fefo_stock)
        self.assertIn(unit_newer, fefo_stock)
        self.assertNotIn(unit_incompat, fefo_stock)
        # Verify FEFO ordering: unit_older comes before unit_newer
        self.assertLess(fefo_stock.index(unit_older), fefo_stock.index(unit_newer))


class CrossMatchingViewAndApiTests(TestCase):
    """
    Test suite for Web UI and REST API cross-matching endpoints (SAD Section 4.3).
    """
    def setUp(self):
        self.hospital = User.objects.create_user(
            username='web_hosp',
            email='hosp@web.local',
            role=User.Role.HOSPITAL,
            password='Password123!',
            hospital_name='City General Hospital'
        )
        self.staff = User.objects.create_user(
            username='web_staff',
            email='staff@web.local',
            role=User.Role.STAFF,
            password='StaffPassword123!'
        )
        self.donor = User.objects.create_user(
            username='web_donor',
            email='donor@web.local',
            role=User.Role.DONOR,
            password='DonorPassword123!',
            blood_group='O+'
        )

        self.requisition = submit_requisition(
            actor=self.hospital,
            blood_group='O+',
            component_type=ComponentType.RBC,
            quantity=1,
            required_by=timezone.localdate() + timedelta(days=2),
        )
        review_requisition(self.requisition.pk, actor=self.staff, action='approve')
        self.requisition.refresh_from_db()

    def _create_unit(self, blood_group):
        unit = BloodUnit.objects.create(
            bag_id=BloodUnit.generate_unique_bag_id(),
            donor=self.donor,
            blood_group=blood_group,
            component_type=ComponentType.RBC,
            volume_ml=250,
            collection_date=timezone.now(),
            status=BloodUnitStatus.AVAILABLE,
            expiry_date=timezone.now() + timedelta(days=40),
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

    def test_staff_can_view_cross_matching_panel_on_detail(self):
        """Staff viewing an approved requisition sees compatibility badges and cross-match form."""
        self.client.login(username='web_staff', password='StaffPassword123!')
        url = reverse('requisitions:detail', kwargs={'pk': self.requisition.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Cross-Match &amp; Override")
        self.assertContains(response, "Compatible Groups")
        self.assertContains(response, "O-")
        self.assertContains(response, "O+")

    def test_staff_post_cross_match_compatible_success(self):
        """Staff submitting compatible unit through HTML form records decision."""
        unit_o_neg = self._create_unit('O-')
        self.client.login(username='web_staff', password='StaffPassword123!')
        url = reverse('requisitions:cross_match', kwargs={'pk': self.requisition.pk})

        response = self.client.post(url, {'bag_id': unit_o_neg.bag_id}, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Cross-match successful")
        self.assertTrue(CrossMatchDecision.objects.filter(blood_unit=unit_o_neg).exists())

    def test_staff_post_cross_match_incompatible_without_override_fails(self):
        """Incompatible unit submitted without override shows error on detail page."""
        unit_a_pos = self._create_unit('A+')
        self.client.login(username='web_staff', password='StaffPassword123!')
        url = reverse('requisitions:cross_match', kwargs={'pk': self.requisition.pk})

        response = self.client.post(url, {'bag_id': unit_a_pos.bag_id, 'override_reason': ''}, follow=True)
        self.assertEqual(response.status_code, 400)
        self.assertContains(response, "INCOMPATIBLE", status_code=400)

    def test_api_cross_match_endpoint_success(self):
        """POST /api/requests/{id}/cross-match per SAD Section 4.3 records decision."""
        unit_o_pos = self._create_unit('O+')
        self.client.login(username='web_staff', password='StaffPassword123!')
        url = f"/api/requests/{self.requisition.pk}/cross-match/"

        payload = {'bagId': unit_o_pos.bag_id}
        response = self.client.post(url, data=json.dumps(payload), content_type='application/json')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        self.assertEqual(data['outcome'], CrossMatchOutcome.COMPATIBLE)
        self.assertTrue(data['isCompatible'])
        self.assertFalse(data['isOverridden'])

    def test_api_cross_match_endpoint_incompatible_with_override(self):
        """POST /api/requests/{id}/cross-match with incompatible unit and overrideReason returns 201."""
        unit_b_pos = self._create_unit('B+')
        self.client.login(username='web_staff', password='StaffPassword123!')
        url = f"/api/requests/{self.requisition.pk}/cross-match/"

        payload = {
            'bagId': unit_b_pos.bag_id,
            'overrideReason': 'Special clinical authorization',
        }
        response = self.client.post(url, data=json.dumps(payload), content_type='application/json')
        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertTrue(data['success'])
        self.assertEqual(data['outcome'], CrossMatchOutcome.OVERRIDDEN)
        self.assertFalse(data['isCompatible'])
        self.assertTrue(data['isOverridden'])
        self.assertEqual(data['overrideReason'], 'Special clinical authorization')

    def test_api_cross_match_endpoint_forbidden_for_hospital(self):
        """Hospital users cannot access /api/requests/{id}/cross-match (403 Forbidden)."""
        unit = self._create_unit('O+')
        self.client.login(username='web_hosp', password='Password123!')
        url = f"/api/requests/{self.requisition.pk}/cross-match/"

        response = self.client.post(url, data=json.dumps({'bagId': unit.bag_id}), content_type='application/json')
        self.assertEqual(response.status_code, 403)
