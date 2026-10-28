from datetime import timedelta
from unittest.mock import patch

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from accounts.models import User
from requisitions.models import Requisition, RequisitionEvent
from requisitions.services import (
    RequisitionConflict, pending_stat_summary, review_requisition, set_priority, visible_requisitions,
)
from .base import RequestTestCase


class SubmissionTests(RequestTestCase):
    def test_unique_pending_requests_and_submission_event(self):
        first, second = self.submit(), self.submit()
        self.assertNotEqual(first.requisition_id, second.requisition_id)
        self.assertEqual(first.hospital, self.hospital)
        self.assertEqual(first.status, Requisition.Status.PENDING)
        self.assertEqual(first.remaining_quantity, 2)
        event = first.events.get()
        self.assertEqual(event.actor, self.hospital)
        self.assertEqual(event.actor_label, self.hospital.username)
        self.assertEqual(event.action, 'Submitted')
        self.assertTrue(timezone.is_aware(event.created_at))

    def test_validation_and_atomic_submission_audit(self):
        for overrides in [{'quantity': 0}, {'quantity': -1}, {'quantity': True}, {'quantity': 1.5},
                          {'blood_group': 'invalid'}, {'component_type': 'invalid'}, {'is_stat': 'yes'},
                          {'required_by': timezone.localdate() - timedelta(days=1)}]:
            with self.subTest(overrides=overrides), self.assertRaises(ValidationError):
                self.submit(**overrides)
        self.assertEqual(Requisition.objects.count(), 0)
        with patch('requisitions.services._event', side_effect=RuntimeError('audit unavailable')):
            with self.assertRaises(RuntimeError):
                self.submit()
        self.assertEqual(Requisition.objects.count(), 0)

    def test_zero_quantity_rejected_at_database_boundary(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Requisition.objects.create(hospital=self.hospital, **self.request_data(quantity=0))

    def test_actor_permissions_are_rechecked_from_database(self):
        for actor in [self.staff, self.donor, self.admin_user]:
            with self.subTest(role=actor.role), self.assertRaises(PermissionDenied):
                self.submit(actor=actor)
        User.objects.filter(pk=self.hospital.pk).update(is_approved=False)
        with self.assertRaises(PermissionDenied):
            self.submit()  # The caller's cached user still claims to be approved.
        User.objects.filter(pk=self.hospital.pk).update(is_approved=True, is_active=False)
        with self.assertRaises(PermissionDenied):
            self.submit()

    def test_hospital_visibility_is_scoped_and_staff_sees_both(self):
        first, second = self.submit(), self.submit(actor=self.other)
        self.assertEqual(list(visible_requisitions(self.hospital)), [first])
        self.assertEqual(list(visible_requisitions(self.other)), [second])
        self.assertEqual(set(visible_requisitions(self.staff)), {first, second})
        self.donor.is_staff = True
        self.donor.save()
        with self.assertRaises(PermissionDenied):
            visible_requisitions(self.donor)


class ReviewAndPriorityTests(RequestTestCase):
    def test_approval_and_rejection_are_audited_with_actor_and_reason(self):
        approved, rejected = self.submit(), self.submit()
        approved = review_requisition(approved.pk, actor=self.staff, action='approve', expected_version=0)
        rejected = review_requisition(
            rejected.pk, actor=self.admin_user, action='reject', reason=' No stock ', expected_version=0,
        )
        self.assertEqual(approved.status, 'Approved')
        self.assertEqual(approved.reviewed_by, self.staff)
        self.assertIsNotNone(approved.reviewed_at)
        self.assertEqual(rejected.rejection_reason, 'No stock')
        self.assertEqual(rejected.events.last().actor, self.admin_user)
        self.assertEqual(rejected.events.last().previous_status, 'Pending')
        self.assertEqual(rejected.events.last().note, 'No stock')
        with self.assertRaises(RequisitionConflict):
            review_requisition(approved.pk, actor=self.staff, action='reject', reason='Late change')

    def test_invalid_review_or_missing_reason_has_no_side_effects(self):
        requisition = self.submit()
        for action, reason in [('reject', '  '), ('fulfil', ''), ('approve', 1)]:
            with self.subTest(action=action, reason=reason), self.assertRaises(ValidationError):
                review_requisition(requisition.pk, actor=self.staff, action=action, reason=reason)
        requisition.refresh_from_db()
        self.assertEqual((requisition.status, requisition.version, requisition.events.count()), ('Pending', 0, 1))
        for actor in [self.hospital, self.donor]:
            with self.assertRaises(PermissionDenied):
                review_requisition(requisition.pk, actor=actor, action='approve')

    def test_stale_review_cannot_overwrite_priority_change(self):
        requisition = self.submit()
        changed = set_priority(requisition.pk, actor=self.hospital, is_stat=True, expected_version=0)
        with self.assertRaises(RequisitionConflict):
            review_requisition(requisition.pk, actor=self.staff, action='approve', expected_version=0)
        approved = review_requisition(requisition.pk, actor=self.staff, action='approve', expected_version=changed.version)
        self.assertEqual(approved.status, 'Approved')

    def test_priority_ownership_no_op_and_pending_only(self):
        requisition = self.submit()
        with self.assertRaises(PermissionDenied):
            set_priority(requisition.pk, actor=self.other, is_stat=True)
        with self.assertRaises(ValidationError):
            set_priority(requisition.pk, actor=self.hospital, is_stat='true')
        set_priority(requisition.pk, actor=self.hospital, is_stat=False, expected_version=0)
        self.assertEqual(requisition.events.count(), 1)
        review_requisition(requisition.pk, actor=self.staff, action='approve')
        with self.assertRaises(RequisitionConflict):
            set_priority(requisition.pk, actor=self.hospital, is_stat=True)

    def test_stat_queue_and_alerts_follow_submission_and_review(self):
        ordinary = self.submit()
        urgent = self.submit(actor=self.other, is_stat=True)
        urgent2 = self.submit(is_stat=True)
        self.assertEqual(list(visible_requisitions(self.staff)), [urgent, urgent2, ordinary])
        summary = pending_stat_summary(self.staff)
        self.assertEqual((summary['count'], summary['latest_id']), (2, urgent2.requisition_id))
        review_requisition(urgent2.pk, actor=self.staff, action='approve')
        self.assertEqual(pending_stat_summary(self.staff)['count'], 1)
        with self.assertRaises(PermissionDenied):
            pending_stat_summary(self.hospital)

    def test_events_cannot_be_edited_or_deleted(self):
        event = self.submit().events.get()
        with self.assertRaises(ValidationError):
            event.save()
        with self.assertRaises(ValidationError):
            event.delete()
        with self.assertRaises(ValidationError):
            RequisitionEvent.objects.filter(pk=event.pk).update(note='changed')
        with self.assertRaises(ValidationError):
            RequisitionEvent.objects.filter(pk=event.pk).delete()
        with self.assertRaises(ValidationError):
            RequisitionEvent.objects.bulk_update([event], ['note'])
        with self.assertRaises(ValidationError):
            RequisitionEvent(pk=event.pk).save()
        with self.assertRaises(ValidationError):
            RequisitionEvent.objects.bulk_create([event], update_conflicts=True, update_fields=['note'], unique_fields=['pk'])
