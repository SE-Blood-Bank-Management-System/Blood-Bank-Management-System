from unittest.mock import patch

from django.contrib.admin.sites import AdminSite
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError
from django.test import RequestFactory, TestCase

from accounts.models import User
from .admin import BloodUnitAdmin, StatusChangeAdmin
from .models import BloodUnit, BloodUnitStatus, StatusChange


class StatusHistoryIntegrityTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.staff = User.objects.create_user('integrity_staff', role=User.Role.STAFF)

    def setUp(self):
        self.unit = BloodUnit.objects.create(blood_group='O+', collected_by=self.staff)

    def test_queryset_status_updates_and_bulk_updates_cannot_bypass_history(self):
        with self.assertRaises(ValidationError):
            BloodUnit.objects.filter(pk=self.unit.pk).update(status=BloodUnitStatus.DISCARDED)
        self.unit.status = BloodUnitStatus.DISCARDED
        with self.assertRaises(ValidationError):
            BloodUnit.objects.bulk_update([self.unit], ['status'])
        self.unit.refresh_from_db()
        self.assertEqual(self.unit.status, BloodUnitStatus.QUARANTINED)

    def test_bulk_import_creates_history_and_blocks_conflicting_upserts(self):
        units = BloodUnit.objects.bulk_create([BloodUnit(blood_group='A+'), BloodUnit(blood_group='B+')])
        self.assertTrue(all(unit.status_changes.count() == 1 for unit in units))
        self.assertTrue(all(unit.quarantined_at is not None for unit in units))
        with self.assertRaises(ValidationError):
            BloodUnit.objects.bulk_create([BloodUnit(bag_id=self.unit.bag_id)], ignore_conflicts=True)

    def test_status_history_is_append_only(self):
        event = self.unit.status_changes.get()
        event.reason = 'Changed'
        for operation in [event.save, event.delete, lambda: StatusChange.objects.filter(pk=event.pk).delete(),
                          lambda: StatusChange.objects.filter(pk=event.pk).update(reason='Changed')]:
            with self.assertRaises(ValidationError):
                operation()
        clone = StatusChange(pk=event.pk, blood_unit=self.unit, new_status='Discarded', actor_label='Forged')
        with self.assertRaises(IntegrityError), transaction.atomic():
            clone.save()
        with self.assertRaises(ValidationError):
            StatusChange.objects.bulk_create([clone], update_conflicts=True, update_fields=['reason'], unique_fields=['pk'])
        event.refresh_from_db()
        self.assertEqual(event.actor_label, 'integrity_staff')

    def test_actor_snapshot_survives_account_rename_and_deletion(self):
        event = self.unit.status_changes.get()
        self.staff.username = 'renamed_staff'
        self.staff.save()
        self.staff.delete()
        event.refresh_from_db()
        self.assertIsNone(event.changed_by_id)
        self.assertEqual(event.actor_label, 'integrity_staff')

    def test_unit_deletion_cannot_remove_status_history(self):
        with self.assertRaises(ProtectedError):
            self.unit.delete()
        self.assertEqual(self.unit.status_changes.count(), 1)

    def test_admin_save_records_actual_request_user_and_history_admin_is_read_only(self):
        request = RequestFactory().post('/admin/')
        request.user = self.staff
        self.unit.status = BloodUnitStatus.EXPIRED
        BloodUnitAdmin(BloodUnit, AdminSite()).save_model(request, self.unit, None, True)
        self.assertEqual(self.unit.status_changes.first().changed_by, self.staff)
        history_admin = StatusChangeAdmin(StatusChange, AdminSite())
        self.assertFalse(history_admin.has_add_permission(request))
        self.assertFalse(history_admin.has_change_permission(request))
        self.assertFalse(history_admin.has_delete_permission(request))

    def test_partial_invalid_serology_panel_rolls_back_earlier_results(self):
        with self.assertRaises(ValidationError):
            self.unit.record_serology_panel({'HIV': 'Pass', 'Invalid test': 'Pass'}, staff_user=self.staff)
        self.assertEqual(self.unit.serology_tests.count(), 0)

    def test_direct_audit_failure_rolls_back_unit_state(self):
        self.unit.status = BloodUnitStatus.DISCARDED
        with patch.object(StatusChange, 'save', side_effect=RuntimeError('Audit failure')):
            with self.assertRaises(RuntimeError):
                self.unit.save(actor=self.staff)
        self.unit.refresh_from_db()
        self.assertEqual(self.unit.status, BloodUnitStatus.QUARANTINED)
