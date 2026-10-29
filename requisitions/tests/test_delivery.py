"""TC-REQ-02 / TC-DEL-01: ownership, custody and dispatch integration."""
import json
from unittest.mock import patch

from django.core.exceptions import PermissionDenied, ValidationError
from django.test import Client
from django.urls import reverse

from inventory.models import BloodUnitStatus, StatusChange
from inventory.services import allocate_units_to_requisition, dispatch_allocated_units, get_inventory_counts
from requisitions.models import DeliveryConfirmation
from requisitions.services import RequisitionConflict, confirm_receipt
from . import test_fulfilment
from .base import RequestTestCase


class DeliveryFixture(RequestTestCase):
    approved = test_fulfilment.FulfilmentContractTests.approved
    unit = test_fulfilment.FulfilmentContractTests.unit

    def shipment(self, quantity=2):
        req = self.approved(quantity=quantity)
        units = [self.unit(status=BloodUnitStatus.AVAILABLE) for _ in range(quantity)]
        allocate_units_to_requisition(requisition_pk=req.pk, unit_ids=[u.pk for u in units], actor=self.staff)
        manifest, req = dispatch_allocated_units(
            requisition_pk=req.pk, unit_ids=[u.pk for u in units], actor=self.staff, notes='Uttam dispatch.',
        )
        return req, units, manifest


class DeliveryTests(DeliveryFixture):
    def test_receipt_keeps_fulfilment_and_available_counts_and_records_identity(self):
        req, units, manifest = self.shipment()
        before = get_inventory_counts()
        updated = confirm_receipt(req.pk, actor=self.hospital, bag_ids=[units[0].bag_id], expected_version=req.version)
        units[0].refresh_from_db()
        units[1].refresh_from_db()
        receipt = DeliveryConfirmation.objects.get()
        self.assertEqual((receipt.received_by, receipt.receiver_label), (self.hospital, self.hospital.username))
        self.assertIsNotNone(receipt.received_at)
        self.assertEqual((units[0].status, units[1].status), ('Delivered', 'Dispatched'))
        self.assertEqual((updated.status, updated.dispatched_quantity, updated.remaining_quantity), ('Fulfilled', 2, 0))
        self.assertEqual(get_inventory_counts(), before)
        history = StatusChange.objects.get(blood_unit=units[0], new_status='Delivered')
        self.assertEqual((history.previous_status, history.changed_by), ('Dispatched', self.hospital))
        self.assertEqual(updated.events.latest('pk').actor, self.hospital)
        self.assertIn(units[0].bag_id, updated.events.latest('pk').note)
        confirm_receipt(req.pk, actor=self.hospital, bag_ids=[units[1].bag_id], expected_version=updated.version)
        self.assertEqual(DeliveryConfirmation.objects.count(), 2)
        self.assertEqual(manifest.units.count(), 2)

    def test_partial_dispatch_receipt_does_not_fulfil_remaining_quantity(self):
        req = self.approved(quantity=2)
        unit = self.unit(status=BloodUnitStatus.AVAILABLE)
        allocate_units_to_requisition(requisition_pk=req.pk, unit_ids=[unit.pk], actor=self.staff)
        _, req = dispatch_allocated_units(requisition_pk=req.pk, unit_ids=[unit.pk], actor=self.staff)
        result = confirm_receipt(req.pk, actor=self.hospital, bag_ids=[unit.bag_id])
        self.assertEqual((result.status, result.dispatched_quantity, result.remaining_quantity),
                         ('Partially Fulfilled', 1, 1))

    def test_duplicate_stale_and_mixed_batches_are_atomic(self):
        req, units, _ = self.shipment()
        first = confirm_receipt(req.pk, actor=self.hospital, bag_ids=[units[0].bag_id])
        for bags, version in [([units[0].bag_id], first.version),
                              ([units[0].bag_id, units[1].bag_id], first.version),
                              ([units[1].bag_id], req.version)]:
            with self.subTest(bags=bags, version=version), self.assertRaises(RequisitionConflict):
                confirm_receipt(req.pk, actor=self.hospital, bag_ids=bags, expected_version=version)
        req.refresh_from_db()
        units[1].refresh_from_db()
        self.assertEqual((req.version, units[1].status), (first.version, 'Dispatched'))
        self.assertEqual(DeliveryConfirmation.objects.count(), 1)

    def test_rejects_foreign_unknown_duplicate_and_non_dispatched_bags(self):
        req, units, _ = self.shipment()
        foreign, foreign_units, _ = self.shipment(1)
        for bags in [[], 'bag', [True], [units[0].bag_id] * 2, ['missing'],
                     [units[0].bag_id, foreign_units[0].bag_id]]:
            with self.subTest(bags=bags), self.assertRaises(ValidationError):
                confirm_receipt(req.pk, actor=self.hospital, bag_ids=bags)
        units[1].status = BloodUnitStatus.DISCARDED
        units[1].save(actor=self.staff)
        with self.assertRaises(RequisitionConflict):
            confirm_receipt(req.pk, actor=self.hospital, bag_ids=[u.bag_id for u in units])
        self.assertFalse(DeliveryConfirmation.objects.exists())
        units[0].refresh_from_db()
        self.assertEqual(units[0].status, 'Dispatched')

    def test_only_active_approved_owner_can_confirm(self):
        req, units, _ = self.shipment(1)
        for actor in [self.other, self.staff, self.admin_user, self.donor]:
            with self.subTest(actor=actor), self.assertRaises(PermissionDenied):
                confirm_receipt(req.pk, actor=actor, bag_ids=[units[0].bag_id])
        self.hospital.is_approved = False
        self.hospital.save(update_fields=['is_approved'])
        with self.assertRaises(PermissionDenied):
            confirm_receipt(req.pk, actor=self.hospital, bag_ids=[units[0].bag_id])
        self.assertFalse(DeliveryConfirmation.objects.exists())

    def test_hospital_cannot_bypass_receipt_service_with_unit_save(self):
        _, units, _ = self.shipment(1)
        units[0].status = BloodUnitStatus.DELIVERED
        with self.assertRaises(PermissionDenied):
            units[0].save(actor=self.hospital)

    def test_failure_in_audit_rolls_back_receipt_status_and_version(self):
        req, units, _ = self.shipment(1)
        with patch('requisitions.services._event', side_effect=RuntimeError('audit unavailable')):
            with self.assertRaises(RuntimeError):
                confirm_receipt(req.pk, actor=self.hospital, bag_ids=[units[0].bag_id])
        units[0].refresh_from_db()
        current_version = req.version
        req.refresh_from_db()
        self.assertEqual((units[0].status, req.version), ('Dispatched', current_version))
        self.assertFalse(DeliveryConfirmation.objects.exists())
        self.assertFalse(StatusChange.objects.filter(new_status='Delivered').exists())

    def test_receipt_history_cannot_be_rewritten_or_deleted(self):
        req, units, _ = self.shipment(1)
        confirm_receipt(req.pk, actor=self.hospital, bag_ids=[units[0].bag_id])
        receipt = DeliveryConfirmation.objects.get()
        for change in [lambda: receipt.save(), lambda: receipt.delete(),
                       lambda: DeliveryConfirmation.objects.update(receiver_label='other'),
                       lambda: DeliveryConfirmation.objects.all().delete()]:
            with self.assertRaises(ValidationError):
                change()


class DeliveryWebTests(DeliveryFixture):
    def test_tracking_page_api_and_html_confirmation(self):
        req, units, manifest = self.shipment(1)
        self.client.force_login(self.hospital)
        detail = reverse('requisitions:detail', args=[req.pk])
        page = self.client.get(detail)
        for text in [units[0].bag_id, manifest.manifest_id, 'Confirm selected bags received']:
            self.assertContains(page, text)
        response = self.client.post(reverse('requisitions:receipt', args=[req.pk]),
                                    {'bag_ids': [units[0].bag_id], 'version': req.version})
        self.assertRedirects(response, detail)
        self.assertContains(self.client.get(detail), 'Delivered')
        data = self.client.get(reverse('requisition_api:detail', args=[req.pk])).json()
        self.assertEqual(data['deliveries'][0]['receivedBy'], self.hospital.username)
        self.assertEqual(data['dispatches'][0]['bagIds'], [units[0].bag_id])
        self.assertEqual(data['allocations'][0]['unitStatus'], 'Delivered')
        self.client.force_login(self.staff)
        self.assertContains(self.client.get(detail), self.hospital.username)
        self.assertNotContains(self.client.get(detail), 'Confirm selected bags received')

    def test_canonical_delivery_api_and_repeated_submission(self):
        req, units, _ = self.shipment(1)
        item = req.fulfilments.get()
        url = reverse('api_confirm_delivery', args=[item.pk])
        self.client.force_login(self.hospital)
        data = json.dumps({'version': req.version})
        self.assertEqual(self.client.post(url, data, content_type='application/json').status_code, 200)
        self.assertEqual(self.client.post(url, data, content_type='application/json').status_code, 409)
        self.assertEqual(DeliveryConfirmation.objects.count(), 1)

    def test_foreign_tracking_and_confirmation_are_hidden_and_csrf_enforced(self):
        req, units, _ = self.shipment(1)
        url = reverse('api_confirm_delivery', args=[req.fulfilments.get().pk])
        self.client.force_login(self.other)
        for path in [reverse('requisitions:detail', args=[req.pk]),
                     reverse('requisition_api:detail', args=[req.pk])]:
            self.assertEqual(self.client.get(path).status_code, 404)
        self.assertEqual(self.client.post(url, '{}', content_type='application/json').status_code, 404)
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.hospital)
        self.assertEqual(client.post(url, '{}', content_type='application/json').status_code, 403)
        self.client.force_login(self.staff)
        self.assertEqual(self.client.post(url, '{}', content_type='application/json').status_code, 403)

    def test_invalid_payload_and_invalid_form_have_no_side_effects(self):
        req, units, _ = self.shipment(1)
        self.client.force_login(self.hospital)
        url = reverse('api_confirm_delivery', args=[req.fulfilments.get().pk])
        for body in [{}, {'version': True}, {'version': -1}, {'version': req.version, 'receivedBy': 'fake'}]:
            self.assertEqual(self.client.post(url, json.dumps(body), content_type='application/json').status_code, 400)
        self.assertEqual(self.client.post(url, 'bad', content_type='application/json').status_code, 400)
        response = self.client.post(reverse('requisitions:receipt', args=[req.pk]),
                                    {'bag_ids': ['foreign'], 'version': req.version})
        self.assertEqual(response.status_code, 400)
        self.assertFalse(DeliveryConfirmation.objects.exists())
