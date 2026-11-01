"""Integrated TC-REQ/MATCH/DISP/DEL/RPT/AUD acceptance, using real services."""
from datetime import timedelta

from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from core.audit import verify_audit_log_integrity
from core.models import SecurityAuditEvent
from core.reports import get_requisition_report_data
from inventory.models import (
    BloodUnit, BloodUnitStatus, ComponentType, REQUIRED_SEROLOGY_TESTS, SerologyTest,
)
from inventory.services import (
    allocate_units_to_requisition, dispatch_allocated_units, get_fefo_allocation_suggestions, get_inventory_counts,
)
from requisitions.services import confirm_receipt, record_cross_match, review_requisition, submit_requisition


class Sprint2IntegrationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.hospital = User.objects.create_user('abhinav', role='HOSPITAL', hospital_name='Abhinav Hospital')
        cls.staff = User.objects.create_user('uttam', role='STAFF')
        cls.admin_user = User.objects.create_user('akshay', role='ADMIN')
        cls.donor = User.objects.create_user('navaneeth', role='DONOR')

    def unit(self, *, component=ComponentType.RBC, group='O+', days=5, status='Available', tested=True):
        unit = BloodUnit.objects.create(
            donor=self.donor, blood_group=group, component_type=component,
            status=status, expiry_date=timezone.now() + timedelta(days=days), location='Uttam Blood Bank',
        )
        if tested:
            for kind in REQUIRED_SEROLOGY_TESTS:
                SerologyTest.objects.create(blood_unit=unit, test_type=kind, result='Pass', tested_by=self.staff)
        return unit

    def request(self, *, component=ComponentType.RBC, group='O+', quantity=2):
        req = submit_requisition(actor=self.hospital, blood_group=group, component_type=component,
                                 quantity=quantity, required_by=timezone.localdate(), is_stat=True)
        return review_requisition(req.pk, actor=self.staff, action='approve')

    def test_partial_then_full_dispatch_receipt_reports_and_audit_reconcile(self):
        req = self.request()
        early, late = self.unit(days=2), self.unit(days=7)
        unsafe = self.unit(status='Quarantined', tested=False)
        expired = self.unit(days=-1)
        self.assertEqual([u.pk for u in get_fefo_allocation_suggestions(req)], [early.pk, late.pk])
        for unit in [unsafe, expired]:
            with self.assertRaises(ValidationError):
                allocate_units_to_requisition(requisition_pk=req.pk, unit_ids=[unit.pk], actor=self.staff)
        for index, unit in enumerate([early, late]):
            decision = record_cross_match(req.pk, unit.bag_id, actor=self.staff)
            self.assertTrue(decision.is_compatible)
            allocate_units_to_requisition(requisition_pk=req.pk, unit_ids=[unit.pk], actor=self.staff)
            manifest, req = dispatch_allocated_units(requisition_pk=req.pk, unit_ids=[unit.pk], actor=self.staff)
            req = confirm_receipt(req.pk, actor=self.hospital, bag_ids=[unit.bag_id], expected_version=req.version)
            self.assertEqual(req.status, 'Partially Fulfilled' if index == 0 else 'Fulfilled')
            self.assertEqual(req.dispatched_quantity, index + 1)
            self.assertEqual(manifest.bag_ids, [unit.bag_id])
        self.assertEqual(get_inventory_counts()['total_units_available'], 0)
        today = timezone.localdate()
        report = get_requisition_report_data(today, today)
        self.assertEqual((report['total_fulfilled'], report['total_units_dispatched'], report['manifests_count']), (1, 2, 2))
        self.assertEqual(req.fulfilments.filter(blood_unit__status='Delivered').count(), 2)
        self.assertTrue(SecurityAuditEvent.objects.filter(target_id=req.requisition_id).exists())
        valid, errors, count = verify_audit_log_integrity()
        self.assertTrue(valid, errors)
        self.assertGreater(count, 0)
        self.client.force_login(self.donor)
        self.assertEqual(self.client.get(reverse('core:reports_dashboard')).status_code, 403)
        self.assertEqual(self.client.get(reverse('core:audit_log')).status_code, 403)
        with self.assertRaises(PermissionDenied):
            confirm_receipt(req.pk, actor=self.staff, bag_ids=[early.bag_id])

    def test_component_compatibility_is_shared_by_cross_match_fefo_and_allocation(self):
        # Existing component policy: AB plasma can supply O; O plasma cannot supply AB.
        for donor, recipient, compatible in [('AB+', 'O+', True), ('O+', 'AB+', False)]:
            with self.subTest(donor=donor, recipient=recipient):
                req = self.request(component=ComponentType.PLASMA, group=recipient, quantity=1)
                unit = self.unit(component=ComponentType.PLASMA, group=donor)
                self.assertEqual(unit.pk in [u.pk for u in get_fefo_allocation_suggestions(req)], compatible)
                if compatible:
                    decision = record_cross_match(req.pk, unit.bag_id, actor=self.staff)
                    self.assertTrue(decision.is_compatible)
                    allocations = allocate_units_to_requisition(
                        requisition_pk=req.pk, unit_ids=[unit.pk], actor=self.staff,
                    )
                    self.assertEqual(allocations[0].cross_match_outcome, 'Compatible')
                else:
                    with self.assertRaises(ValidationError):
                        allocate_units_to_requisition(requisition_pk=req.pk, unit_ids=[unit.pk], actor=self.staff)

