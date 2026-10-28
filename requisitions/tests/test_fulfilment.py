from datetime import timedelta
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.utils import timezone

from inventory.models import (
    BloodUnit, BloodUnitStatus, ComponentType, REQUIRED_SEROLOGY_TESTS, SerologyResult, SerologyTest,
)
from requisitions.models import RequisitionFulfilment
from requisitions.services import RequisitionConflict, record_dispatched_units, review_requisition, visible_requisitions
from .base import RequestTestCase


class FulfilmentContractTests(RequestTestCase):
    def approved(self, **overrides):
        requisition = self.submit(**overrides)
        return review_requisition(requisition.pk, actor=self.staff, action='approve')

    def unit(self, **overrides):
        unit = BloodUnit.objects.create(
            donor=self.donor, blood_group='O+', collection_date=timezone.now(),
            **{'component_type': ComponentType.RBC, 'status': BloodUnitStatus.DISPATCHED,
               'expiry_date': timezone.now() + timedelta(days=2), **overrides},
        )
        SerologyTest.objects.bulk_create([
            SerologyTest(blood_unit=unit, test_type=test_type, result=SerologyResult.PASS, tested_by=self.staff)
            for test_type in REQUIRED_SEROLOGY_TESTS
        ])
        return unit

    def test_real_bag_facts_drive_partial_and_full_status(self):
        requisition = self.approved()
        first, second = self.unit(), self.unit()
        partial = record_dispatched_units(requisition.pk, actor=self.staff, unit_ids=[first.pk])
        self.assertEqual(partial.status, 'Partially Fulfilled')
        self.assertEqual((partial.dispatched_quantity, partial.remaining_quantity), (1, 1))
        full = record_dispatched_units(requisition.pk, actor=self.staff, unit_ids=[second.pk])
        self.assertEqual(full.status, 'Fulfilled')
        self.assertEqual((full.dispatched_quantity, full.remaining_quantity), (2, 0))
        listed = visible_requisitions(self.hospital).get(pk=full.pk)
        self.assertEqual(listed.dispatched_quantity, 2)
        self.assertIn(first.bag_id, partial.events.get(action='Dispatch recorded', new_status='Partially Fulfilled').note)
        self.assertEqual(full.fulfilments.get(blood_unit=second).recorded_by, self.staff)

    def test_same_bag_cannot_be_counted_twice_or_against_another_request(self):
        first, second, unit = self.approved(), self.approved(), self.unit()
        record_dispatched_units(first.pk, actor=self.staff, unit_ids=[unit.pk])
        for requisition in [first, second]:
            with self.assertRaises(RequisitionConflict):
                record_dispatched_units(requisition.pk, actor=self.staff, unit_ids=[unit.pk])
        self.assertEqual(RequisitionFulfilment.objects.count(), 1)
        second.refresh_from_db()
        self.assertEqual((second.status, second.version), ('Approved', 1))

    def test_invalid_mixed_batch_rolls_back_counts_and_audit(self):
        requisition = self.approved()
        valid = self.unit()
        invalid = self.unit(status=BloodUnitStatus.QUARANTINED)
        with self.assertRaises(ValidationError):
            record_dispatched_units(requisition.pk, actor=self.staff, unit_ids=[valid.pk, invalid.pk])
        requisition.refresh_from_db()
        self.assertEqual((requisition.status, requisition.version, requisition.dispatched_quantity), ('Approved', 1, 0))
        self.assertEqual(requisition.events.count(), 2)

    def test_rejects_expired_wrong_component_and_untested_stock(self):
        requisition = self.approved()
        expired = self.unit(expiry_date=timezone.now() - timedelta(seconds=1))
        wrong = self.unit(component_type=ComponentType.PLASMA)
        untested = self.unit()
        untested.serology_tests.all().delete()
        for unit in [expired, wrong, untested]:
            with self.subTest(bag=unit.bag_id), self.assertRaises(ValidationError):
                record_dispatched_units(requisition.pk, actor=self.staff, unit_ids=[unit.pk])
        self.assertEqual(requisition.fulfilments.count(), 0)

    def test_requires_approval_distinct_units_and_remaining_capacity(self):
        requisition, unit = self.submit(quantity=1), self.unit()
        with self.assertRaises(RequisitionConflict):
            record_dispatched_units(requisition.pk, actor=self.staff, unit_ids=[unit.pk])
        review_requisition(requisition.pk, actor=self.staff, action='approve')
        for unit_ids in [[], [unit.pk, unit.pk], [True], [unit.pk, self.unit().pk], [999999]]:
            with self.subTest(unit_ids=unit_ids), self.assertRaises(ValidationError):
                record_dispatched_units(requisition.pk, actor=self.staff, unit_ids=unit_ids)
        self.assertEqual(requisition.fulfilments.count(), 0)

    def test_dispatch_recording_rolls_back_when_audit_fails(self):
        requisition, unit = self.approved(), self.unit()
        with patch('requisitions.services._event', side_effect=RuntimeError('audit unavailable')):
            with self.assertRaises(RuntimeError):
                record_dispatched_units(requisition.pk, actor=self.staff, unit_ids=[unit.pk])
        requisition.refresh_from_db()
        self.assertEqual((requisition.status, requisition.version), ('Approved', 1))
        self.assertFalse(requisition.fulfilments.exists())
