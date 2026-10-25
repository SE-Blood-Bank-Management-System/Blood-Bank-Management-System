from datetime import timedelta
from unittest.mock import patch

from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase
from django.utils import timezone

from accounts.models import User
from .models import BloodUnit, BloodUnitStatus, REQUIRED_SEROLOGY_TESTS, SerologyTest, StatusChange


class StatusTransitionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.staff = User.objects.create_user('audit_staff', role=User.Role.STAFF)
        cls.donor = User.objects.create_user('audit_donor')

    def setUp(self):
        self.unit = BloodUnit.objects.create(blood_group='O+', donor=self.donor)

    def test_collection_creates_initial_entry_with_recording_staff(self):
        unit = BloodUnit.record_collection(self.staff, self.donor, 'A+')
        event = unit.status_changes.get()
        self.assertEqual((event.previous_status, event.new_status), ('', 'Quarantined'))
        self.assertEqual(event.changed_by, self.staff)
        self.assertEqual(event.actor_label, 'audit_staff')
        self.assertEqual(unit.quarantined_at, unit.collection_date)

    def test_direct_change_logs_persisted_states_actor_and_time(self):
        before = timezone.now()
        self.unit.status = BloodUnitStatus.DISCARDED
        self.unit.save(actor=self.staff, status_reason='Storage issue.')
        event = self.unit.status_changes.first()
        self.assertEqual((event.previous_status, event.new_status), ('Quarantined', 'Discarded'))
        self.assertEqual(event.changed_by_id, self.staff.pk)
        self.assertEqual(event.reason, 'Storage issue.')
        self.assertGreaterEqual(event.changed_at, before)
        self.assertIsNone(self.unit.quarantined_at)
        self.assertEqual(self.unit.status_changes.count(), 2)

    def test_noop_and_unrelated_partial_updates_do_not_invent_events(self):
        self.unit.save(actor=self.staff)
        self.unit.status = BloodUnitStatus.DISCARDED
        self.unit.location = 'Updated location'
        self.unit.save(update_fields=['location'], actor=self.staff)
        self.unit.refresh_from_db()
        self.assertEqual(self.unit.status, BloodUnitStatus.QUARANTINED)
        self.assertEqual(self.unit.status_changes.count(), 1)
        self.unit.status = BloodUnitStatus.DISCARDED
        self.unit.save(update_fields=['status'], actor=self.staff)
        self.assertEqual(self.unit.status_changes.count(), 2)

    def test_serology_transitions_record_staff_without_duplicate_events(self):
        panel = {test: 'Pass' for test in REQUIRED_SEROLOGY_TESTS}
        self.unit.record_serology_panel(panel, staff_user=self.staff)
        event = self.unit.status_changes.first()
        self.assertEqual(event.new_status, BloodUnitStatus.AVAILABLE)
        self.assertEqual(event.changed_by, self.staff)
        self.unit.record_serology_panel(panel, staff_user=self.staff)
        self.assertEqual(self.unit.status_changes.count(), 2)
        self.unit.record_serology_test('HIV', 'Fail', staff_user=self.staff)
        self.assertEqual(self.unit.status_changes.first().previous_status, BloodUnitStatus.AVAILABLE)
        self.assertEqual(self.unit.status_changes.first().new_status, BloodUnitStatus.DISCARDED)

    def test_return_to_quarantine_resets_elapsed_time(self):
        self.unit.record_serology_panel({t: 'Pass' for t in REQUIRED_SEROLOGY_TESTS}, staff_user=self.staff)
        SerologyTest.objects.filter(blood_unit=self.unit, test_type='HIV').delete()
        entry_time = timezone.now()
        with patch('inventory.models.timezone.now', return_value=entry_time):
            self.unit.evaluate_serology_status(actor=self.staff)
        self.unit.refresh_from_db()
        self.assertEqual(self.unit.quarantined_at, entry_time)
        self.assertEqual(self.unit.status_changes.first().changed_at, entry_time)
        with patch('inventory.models.timezone.now', return_value=entry_time + timedelta(hours=12)):
            self.assertEqual(self.unit.quarantine_duration_days, 0.5)

    def test_dry_run_does_not_write_history_until_saved(self):
        SerologyTest.objects.bulk_create([
            SerologyTest(blood_unit=self.unit, test_type=t, result='Pass') for t in REQUIRED_SEROLOGY_TESTS
        ])
        self.unit.evaluate_serology_status(actor=self.staff, save=False)
        self.assertEqual(self.unit.status_changes.count(), 1)
        self.assertEqual(BloodUnit.objects.get(pk=self.unit.pk).status, BloodUnitStatus.QUARANTINED)
        self.unit.save()
        self.assertEqual(self.unit.status_changes.first().changed_by, self.staff)

    def test_unauthorized_actor_and_unknown_status_are_rejected(self):
        self.unit.status = BloodUnitStatus.DISCARDED
        with self.assertRaises(PermissionDenied):
            self.unit.save(actor=self.donor)
        self.unit.status = 'Unknown'
        with self.assertRaises(ValidationError):
            self.unit.save(actor=self.staff)
        self.assertEqual(self.unit.status_changes.count(), 1)

    def test_stale_instances_use_actual_previous_status_and_preserve_history(self):
        stale = BloodUnit.objects.get(pk=self.unit.pk)
        self.unit.status = BloodUnitStatus.EXPIRED
        self.unit.save(actor=self.staff)
        stale.status = BloodUnitStatus.DISCARDED
        stale.save(actor=self.staff)
        self.assertEqual(stale.status_changes.first().previous_status, BloodUnitStatus.EXPIRED)
        self.assertEqual(stale.status_changes.count(), 3)
        self.assertIn('Expired', stale.status_audit_log)

    def test_history_failure_rolls_back_status_and_serology_panel(self):
        with patch.object(StatusChange, 'save', side_effect=RuntimeError('Audit insert failure')):
            with self.assertRaises(RuntimeError):
                self.unit.record_serology_panel({t: 'Pass' for t in REQUIRED_SEROLOGY_TESTS}, staff_user=self.staff)
        self.unit.refresh_from_db()
        self.assertEqual(self.unit.status, BloodUnitStatus.QUARANTINED)
        self.assertEqual(self.unit.serology_tests.count(), 0)
        self.assertEqual(self.unit.status_changes.count(), 1)
