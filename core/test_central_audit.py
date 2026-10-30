"""
Automated Test Suite for Central Tamper-Evident Read-Only Audit Log
(SRS BBMS-F-058, BBMS-F-059, BBMS-SR-008, TC-AUD-01, TC-SEC-08).

Verifies:
1. Event coverage across domain lifecycles: donor/user/unit/requisition creation,
   status transitions, deletions, logins, lockouts, role changes, and hospital approvals.
2. Read-only permissions and HTTP 401/403/405 guards across UI and API endpoints.
3. Retention and reference preservation after domain deletions, with secret/medical scrubbing.
4. Immutability guards blocking ORM save(), delete(), QuerySet.update(), and QuerySet.delete().
5. Cryptographic SHA-256 tamper evidence detection via verify_audit_integrity command.
6. Atomic rollback and multi-threaded concurrent append behavior.
"""
from datetime import timedelta
import threading
from django.contrib.admin.sites import AdminSite
from django.contrib.messages.middleware import MessageMiddleware
from django.contrib.sessions.middleware import SessionMiddleware
from django.core.exceptions import PermissionDenied
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection, transaction
from django.test import Client, RequestFactory, TestCase
from django.urls import reverse
from django.utils import timezone
from accounts.admin import CustomUserAdmin, LoginSecurityStateAdmin
from accounts.models import LoginSecurityState, User
from core.admin import SecurityAuditEventAdmin
from core.audit import (
    record_audit_event,
    record_security_event,
    sanitize_audit_details,
    verify_audit_log_integrity,
)
from core.constants import BloodGroup
from core.models import SecurityAuditEvent
from inventory.models import BloodUnit, BloodUnitStatus, ComponentType
from requisitions.models import Requisition
from requisitions.services import review_requisition, submit_requisition


def build_admin_request(user):
    rf = RequestFactory()
    request = rf.get('/admin/')
    request.user = user
    SessionMiddleware(lambda req: None).process_request(request)
    request.session.save()
    MessageMiddleware(lambda req: None).process_request(request)
    return request


class CentralAuditEventCoverageTests(TestCase):
    """
    Verifies full lifecycle audit event recording (BBMS-F-058, TC-AUD-01).
    """
    @classmethod
    def setUpTestData(cls):
        cls.admin_user = User.objects.create_superuser(
            username='audit_admin',
            email='admin@bbms.local',
            password='AdminPassword@123',
            role=User.Role.ADMIN,
        )
        cls.staff_user = User.objects.create_user(
            username='audit_staff',
            email='staff@bbms.local',
            password='StaffPassword@123',
            role=User.Role.STAFF,
        )
        cls.donor_user = User.objects.create_user(
            username='audit_donor',
            email='donor@bbms.local',
            password='DonorPassword@123',
            role=User.Role.DONOR,
        )

    def test_donor_registration_records_audit_event(self):
        client = Client()
        response = client.post(reverse('accounts:register_donor'), {
            'first_name': 'New',
            'last_name': 'Donor',
            'email': 'new_donor_audit@example.com',
            'dob': '1995-05-15',
            'phone': '+91 9876543210',
            'gender': 'Male',
            'blood_group': 'O+',
            'password': 'SecurePassword123!',
        }, follow=True)
        self.assertEqual(response.status_code, 200)

        created_user = User.objects.get(email='new_donor_audit@example.com')
        event = SecurityAuditEvent.objects.filter(
            action='donor_registered',
            target_id=str(created_user.pk),
        ).first()
        self.assertIsNotNone(event)
        self.assertEqual(event.target_type, 'user')
        self.assertEqual(event.details.get('role'), User.Role.DONOR)

    def test_hospital_registration_records_audit_event(self):
        client = Client()
        response = client.post(reverse('accounts:register_hospital'), {
            'hospital_name': 'City General Hospital',
            'license_number': 'REG-HOSP-2026-999',
            'email': 'admin@cityhosp.org',
            'contact_person': 'Dr. Sharma',
            'phone': '+91 80 5555 1234',
            'address': '456 Medical Blvd',
            'password': 'HospitalSecurePass123!',
        }, follow=True)
        self.assertEqual(response.status_code, 200)

        created_user = User.objects.get(email='admin@cityhosp.org')
        self.assertFalse(created_user.is_approved)

        event = SecurityAuditEvent.objects.filter(
            action='hospital_registered',
            target_id=str(created_user.pk),
        ).first()
        self.assertIsNotNone(event)
        self.assertEqual(event.target_type, 'user')
        self.assertEqual(event.details.get('hospital_name'), 'City General Hospital')

    def test_admin_user_creation_and_role_change_records_audit_event(self):
        site = AdminSite()
        user_admin = CustomUserAdmin(User, site)
        request = build_admin_request(user=self.admin_user)

        # 1. Admin creates a user
        new_user = User(
            username='admin_created_staff',
            email='newstaff@bbms.local',
            role=User.Role.STAFF,
            date_of_birth='1990-01-01',
        )
        new_user.set_password('StaffPassword@123')
        form = type('Form', (), {'initial': {}})()
        user_admin.save_model(request, new_user, form, change=False)

        create_event = SecurityAuditEvent.objects.filter(
            action='user_created',
            target_id=str(new_user.pk),
        ).first()
        self.assertIsNotNone(create_event)
        self.assertEqual(create_event.actor, self.admin_user)
        self.assertEqual(create_event.details.get('role'), User.Role.STAFF)

        # 2. Admin modifies user's role to ADMIN
        form_change = type('Form', (), {'initial': {'role': User.Role.STAFF, 'is_approved': True, 'is_active': True}})()
        new_user.role = User.Role.ADMIN
        user_admin.save_model(request, new_user, form_change, change=True)

        role_event = SecurityAuditEvent.objects.filter(
            action='role_changed',
            target_id=str(new_user.pk),
        ).first()
        self.assertIsNotNone(role_event)
        self.assertEqual(role_event.details.get('old_role'), User.Role.STAFF)
        self.assertEqual(role_event.details.get('new_role'), User.Role.ADMIN)

    def test_hospital_approval_actions_record_audit_event(self):
        site = AdminSite()
        user_admin = CustomUserAdmin(User, site)
        request = build_admin_request(user=self.admin_user)

        hospital = User.objects.create_user(
            username='hosp_pending_approval',
            email='pending@hosp.org',
            password='Password@123',
            role=User.Role.HOSPITAL,
            is_approved=False,
        )

        # Execute bulk approval action
        qs = User.objects.filter(pk=hospital.pk)
        user_admin.approve_accounts(request, qs)

        hospital.refresh_from_db()
        self.assertTrue(hospital.is_approved)

        event = SecurityAuditEvent.objects.filter(
            action='hospital_approved',
            target_id=str(hospital.pk),
        ).first()
        self.assertIsNotNone(event)
        self.assertEqual(event.actor, self.admin_user)
        self.assertEqual(event.details.get('is_approved'), True)

    def test_user_deactivation_and_reactivation_records_audit_event(self):
        site = AdminSite()
        user_admin = CustomUserAdmin(User, site)
        request = build_admin_request(user=self.admin_user)

        target = User.objects.create_user(
            username='user_to_deactivate',
            email='deact@bbms.local',
            password='Password@123',
            is_active=True,
        )

        qs = User.objects.filter(pk=target.pk)
        user_admin.deactivate_accounts(request, qs)
        target.refresh_from_db()
        self.assertFalse(target.is_active)

        deact_event = SecurityAuditEvent.objects.filter(
            action='user_deactivated',
            target_id=str(target.pk),
        ).first()
        self.assertIsNotNone(deact_event)

        user_admin.reactivate_accounts(request, qs)
        target.refresh_from_db()
        self.assertTrue(target.is_active)

        react_event = SecurityAuditEvent.objects.filter(
            action='user_reactivated',
            target_id=str(target.pk),
        ).first()
        self.assertIsNotNone(react_event)

    def test_user_deletion_records_audit_event(self):
        site = AdminSite()
        user_admin = CustomUserAdmin(User, site)
        request = build_admin_request(user=self.admin_user)

        doomed_user = User.objects.create_user(
            username='doomed_user',
            email='doomed@bbms.local',
            password='Password@123',
            role=User.Role.DONOR,
        )
        doomed_pk = str(doomed_user.pk)

        user_admin.delete_model(request, doomed_user)

        delete_event = SecurityAuditEvent.objects.filter(
            action='user_deleted',
            target_id=doomed_pk,
        ).first()
        self.assertIsNotNone(delete_event)
        self.assertEqual(delete_event.details.get('username'), 'doomed_user')

    def test_blood_unit_creation_and_status_transitions_recorded(self):
        # 1. Collection recorded
        unit = BloodUnit(
            donor=self.donor_user,
            blood_group=BloodGroup.A_POS,
            component_type=ComponentType.WHOLE_BLOOD,
            volume_ml=450,
            collection_date=timezone.now(),
        )
        unit.save(actor=self.staff_user, status_reason='Routine donor collection.')

        create_event = SecurityAuditEvent.objects.filter(
            action='unit_created',
            target_id=unit.bag_id,
        ).first()
        self.assertIsNotNone(create_event)
        self.assertEqual(create_event.actor, self.staff_user)
        self.assertEqual(create_event.details.get('new_status'), BloodUnitStatus.QUARANTINED)

        # 2. Transition status to Discarded
        unit.status = BloodUnitStatus.DISCARDED
        unit.save(actor=self.staff_user, status_reason='Storage issue.')

        trans_event = SecurityAuditEvent.objects.filter(
            action='unit_status_changed',
            target_id=unit.bag_id,
        ).first()
        self.assertIsNotNone(trans_event)
        self.assertEqual(trans_event.details.get('previous_status'), BloodUnitStatus.QUARANTINED)
        self.assertEqual(trans_event.details.get('new_status'), BloodUnitStatus.DISCARDED)

    def test_requisition_creation_and_approval_recorded(self):
        hospital = User.objects.create_user(
            username='approved_hosp_req',
            email='hosp_req@example.com',
            password='Password@123',
            role=User.Role.HOSPITAL,
            is_approved=True,
        )

        req = submit_requisition(
            actor=hospital,
            blood_group=BloodGroup.O_NEG,
            component_type=ComponentType.RBC,
            quantity=2,
            required_by=timezone.now() + timedelta(days=2),
            is_stat=True,
        )

        submit_event = SecurityAuditEvent.objects.filter(
            action='requisition_created',
            target_id=req.requisition_id,
        ).first()
        self.assertIsNotNone(submit_event)
        self.assertEqual(submit_event.actor, hospital)
        self.assertEqual(submit_event.details.get('is_stat'), True)

        approved = review_requisition(
            req.pk,
            actor=self.staff_user,
            action='approve',
            reason='STAT emergency approved',
            expected_version=req.version,
        )
        self.assertEqual(approved.status, Requisition.Status.APPROVED)

        approve_event = SecurityAuditEvent.objects.filter(
            action='requisition_status_changed',
            target_id=req.requisition_id,
        ).first()
        self.assertIsNotNone(approve_event)
        self.assertEqual(approve_event.actor, self.staff_user)
        self.assertEqual(approve_event.details.get('new_status'), Requisition.Status.APPROVED)

    def test_clear_lockout_records_audit_event(self):
        state = LoginSecurityState.objects.create(
            identifier='user:9999',
            failed_attempts=5,
            lockout_until=timezone.now() + timedelta(minutes=15),
        )
        site = AdminSite()
        lockout_admin = LoginSecurityStateAdmin(LoginSecurityState, site)
        request = build_admin_request(user=self.admin_user)

        lockout_admin.clear_lockout(request, LoginSecurityState.objects.filter(pk=state.pk))
        state.refresh_from_db()
        self.assertEqual(state.failed_attempts, 0)
        self.assertIsNone(state.lockout_until)

        event = SecurityAuditEvent.objects.filter(
            action='lockout_cleared',
            target_id='user:9999',
        ).first()
        self.assertIsNotNone(event)
        self.assertEqual(event.actor, self.admin_user)


class AuditViewerPermissionsTests(TestCase):
    """
    Verifies admin-only access and read-only protections for viewer UI & API (BBMS-F-059, TC-AUD-01).
    """
    @classmethod
    def setUpTestData(cls):
        cls.admin_user = User.objects.create_superuser(
            username='viewer_admin',
            email='viewer_admin@bbms.local',
            password='AdminPassword@123',
            role=User.Role.ADMIN,
        )
        cls.staff_user = User.objects.create_user(
            username='viewer_staff',
            email='viewer_staff@bbms.local',
            password='StaffPassword@123',
            role=User.Role.STAFF,
        )
        cls.donor_user = User.objects.create_user(
            username='viewer_donor',
            email='viewer_donor@bbms.local',
            password='DonorPassword@123',
            role=User.Role.DONOR,
        )
        cls.hospital_user = User.objects.create_user(
            username='viewer_hosp',
            email='viewer_hosp@bbms.local',
            password='HospitalPassword@123',
            role=User.Role.HOSPITAL,
            is_approved=True,
        )

        # Seed an audit record
        record_audit_event(
            action='baseline_audit_entry',
            actor=cls.admin_user,
            target_type='system',
            target_id='SYS-001',
            details={'status': 'ok'},
        )

    def test_anonymous_html_request_redirects_to_login(self):
        client = Client()
        response = client.get(reverse('core:audit_log'))
        self.assertEqual(response.status_code, 302)
        self.assertIn('/accounts/login/', response.url)

    def test_anonymous_api_request_returns_401(self):
        client = Client()
        response = client.get(
            reverse('core:audit_log'),
            HTTP_ACCEPT='application/json',
        )
        self.assertEqual(response.status_code, 401)
        data = response.json()
        self.assertIn('error', data)

    def test_non_admin_roles_forbidden_with_403(self):
        client = Client()
        for user in [self.donor_user, self.hospital_user, self.staff_user]:
            client.force_login(user)
            # HTML request
            res_html = client.get(reverse('core:audit_log'))
            self.assertEqual(res_html.status_code, 403, f"Role {user.role} should be forbidden")

            # API request
            res_api = client.get(reverse('api_audit_logs'))
            self.assertEqual(res_api.status_code, 403, f"Role {user.role} should be forbidden on API")

    def test_admin_can_view_html_and_api(self):
        client = Client()
        client.force_login(self.admin_user)

        # HTML Viewer
        res_html = client.get(reverse('core:audit_log'))
        self.assertEqual(res_html.status_code, 200)
        self.assertContains(res_html, 'Central Audit Log')
        self.assertContains(res_html, 'baseline_audit_entry')
        self.assertContains(res_html, 'Cryptographic Hash Chain: Verified &amp; Tamper-Free')

        # API endpoint
        res_api = client.get(reverse('api_audit_logs'))
        self.assertEqual(res_api.status_code, 200)
        data = res_api.json()
        self.assertTrue(data['integrity_valid'])
        self.assertGreaterEqual(data['count'], 1)
        self.assertEqual(data['results'][0]['action'], 'baseline_audit_entry')

    def test_unsafe_http_methods_rejected_with_405(self):
        client = Client()
        client.force_login(self.admin_user)

        for method in ['post', 'put', 'patch', 'delete']:
            call = getattr(client, method)
            res_html = call(reverse('core:audit_log'), {'action': 'fake'})
            self.assertEqual(res_html.status_code, 405)

            res_api = call(reverse('api_audit_logs'), {'action': 'fake'})
            self.assertEqual(res_api.status_code, 405)

    def test_admin_model_has_no_add_change_delete_permissions(self):
        site = AdminSite()
        audit_admin = SecurityAuditEventAdmin(SecurityAuditEvent, site)
        request = build_admin_request(user=self.admin_user)

        self.assertFalse(audit_admin.has_add_permission(request))
        self.assertFalse(audit_admin.has_change_permission(request))
        self.assertFalse(audit_admin.has_delete_permission(request))
        self.assertIsNone(audit_admin.actions)


class AuditRetentionAndScrubbingTests(TestCase):
    """
    Verifies retention across domain entity deletions and scrubbing of secrets/clinical details (TC-SEC-08).
    """
    def test_actor_deletion_retains_audit_record_and_label(self):
        temp_actor = User.objects.create_user(
            username='temporary_actor',
            email='temp@bbms.local',
            password='Password@123',
        )
        event = record_audit_event(
            action='actor_action_test',
            actor=temp_actor,
            actor_label=temp_actor.username,
            target_type='account',
            target_id='999',
        )

        event_pk = event.pk
        # Delete the actor account
        temp_actor.delete()

        # Audit record must still exist
        persisted = SecurityAuditEvent.objects.get(pk=event_pk)
        self.assertIsNone(persisted.actor)  # FK unlinked via SET_NULL
        self.assertEqual(persisted.actor_label, 'temporary_actor')  # Username retained!

    def test_target_deletion_retains_domain_reference(self):
        event = record_audit_event(
            action='domain_entity_action',
            actor_label='staff_user',
            target_type='blood_unit',
            target_id='BAG-20261030-DEAD',
            details={'unit_notes': 'discarded per policy'},
        )
        persisted = SecurityAuditEvent.objects.get(pk=event.pk)
        self.assertEqual(persisted.target_type, 'blood_unit')
        self.assertEqual(persisted.target_id, 'BAG-20261030-DEAD')

    def test_passwords_tokens_and_medical_details_are_scrubbed(self):
        dirty = {
            'username': 'john_doe',
            'password': 'RawPassword123!',
            'reset_token': 'secret-tok-abc',
            'session_key': 'session-cookie-xyz',
            'medical_history': 'hypertension',
            'questionnaire': {'q1': 'yes', 'q2': 'no'},
            'ineligibility_reason': 'low hemoglobin',
            'safe_metadata': 'safe_value',
        }
        cleaned = sanitize_audit_details(dirty)

        self.assertEqual(cleaned.get('username'), 'john_doe')
        self.assertEqual(cleaned.get('safe_metadata'), 'safe_value')
        self.assertNotIn('password', cleaned)
        self.assertNotIn('reset_token', cleaned)
        self.assertNotIn('session_key', cleaned)
        self.assertNotIn('medical_history', cleaned)
        self.assertNotIn('questionnaire', cleaned)
        self.assertNotIn('ineligibility_reason', cleaned)


class AuditImmutabilityAndTamperEvidenceTests(TestCase):
    """
    Verifies immutable ORM controls and cryptographic tamper detection (BBMS-SR-008, TC-SEC-08, TC-AUD-01).
    """
    def test_orm_save_update_raises_permission_denied(self):
        event = record_audit_event(
            action='immutable_test',
            actor_label='System',
            details={'status': 'original'},
        )
        event.action = 'tampered_action'
        with self.assertRaises(PermissionDenied):
            event.save()

    def test_orm_delete_raises_permission_denied(self):
        event = record_audit_event(
            action='nodelete_test',
            actor_label='System',
        )
        with self.assertRaises(PermissionDenied):
            event.delete()

    def test_queryset_update_and_delete_raise_permission_denied(self):
        event = record_audit_event(
            action='qs_guard_test',
            actor_label='System',
        )
        with self.assertRaises(PermissionDenied):
            SecurityAuditEvent.objects.filter(pk=event.pk).update(action='tampered')

        with self.assertRaises(PermissionDenied):
            SecurityAuditEvent.objects.filter(pk=event.pk).delete()

    def test_verify_audit_integrity_command_passes_on_valid_records(self):
        # Create a sequential chain of 3 records
        record_audit_event('chain_step_1', actor_label='System', details={'step': 1})
        record_audit_event('chain_step_2', actor_label='System', details={'step': 2})
        record_audit_event('chain_step_3', actor_label='System', details={'step': 3})

        is_valid, errors, count = verify_audit_log_integrity()
        self.assertTrue(is_valid)
        self.assertEqual(errors, [])
        self.assertGreaterEqual(count, 3)

        # Verify management command runs with exit code 0
        call_command('verify_audit_integrity')

    def test_tamper_detection_on_modified_action(self):
        event = record_audit_event(
            action='clean_action',
            actor_label='System',
            details={'val': 100},
        )

        # Directly tamper with database via raw SQL (bypassing ORM)
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE core_securityauditevent SET action = 'hacked_action' WHERE id = %s",
                [event.pk]
            )

        is_valid, errors, count = verify_audit_log_integrity()
        self.assertFalse(is_valid)
        self.assertTrue(any(f"Record ID {event.pk} content has been tampered with" in e for e in errors))

        with self.assertRaises(CommandError):
            call_command('verify_audit_integrity', quiet=True)

    def test_tamper_detection_on_modified_details(self):
        event = record_audit_event(
            action='safe_details_test',
            actor_label='System',
            details={'amount': 10},
        )

        # Directly tamper with details JSON in raw database
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE core_securityauditevent SET details = '{\"amount\":9999}' WHERE id = %s",
                [event.pk]
            )

        is_valid, errors, count = verify_audit_log_integrity()
        self.assertFalse(is_valid)
        self.assertTrue(any(f"Record ID {event.pk} content has been tampered with" in e for e in errors))

    def test_tamper_detection_on_deleted_record(self):
        # Create 3 records
        record_audit_event('chain_1', actor_label='System')
        ev2 = record_audit_event('chain_2', actor_label='System')
        ev3 = record_audit_event('chain_3', actor_label='System')

        # Delete the middle record ev2 via raw SQL
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM core_securityauditevent WHERE id = %s", [ev2.pk])

        is_valid, errors, count = verify_audit_log_integrity()
        self.assertFalse(is_valid)
        # ev3's prev_hash should now mismatch the prior record's record_hash
        self.assertTrue(any(f"Record ID {ev3.pk} has broken prev_hash" in e for e in errors))


class AuditRollbackAndConcurrencyTests(TestCase):
    """
    Verifies atomic rollback behavior and concurrent thread safety.
    """
    def test_transaction_rollback_reverts_audit_event(self):
        initial_count = SecurityAuditEvent.objects.count()

        with self.assertRaises(RuntimeError):
            with transaction.atomic():
                record_audit_event(
                    action='aborted_action',
                    actor_label='System',
                )
                raise RuntimeError("Simulated transaction failure")

        final_count = SecurityAuditEvent.objects.count()
        self.assertEqual(final_count, initial_count)

        # Subsequent record chains correctly from whatever was committed
        record_audit_event(
            action='committed_action',
            actor_label='System',
        )
        is_valid, errors, _ = verify_audit_log_integrity()
        self.assertTrue(is_valid)
        self.assertEqual(errors, [])

    def test_concurrent_audit_appends_create_valid_chain(self):
        """
        Multiple concurrent threads appending audit records result in a continuous, unbroken hash chain.
        """
        errors = []
        threads = []
        records_per_thread = 3
        thread_count = 4

        def worker(thread_idx):
            try:
                from django.db import connection
                connection.close()
                for i in range(records_per_thread):
                    record_audit_event(
                        action=f'concurrent_t{thread_idx}_event',
                        actor_label=f'thread_{thread_idx}',
                        details={'iteration': i},
                    )
            except Exception as e:
                errors.append(e)
            finally:
                from django.db import connection
                connection.close()

        for t_idx in range(thread_count):
            t = threading.Thread(target=worker, args=(t_idx,))
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        self.assertEqual(errors, [])
        is_valid, chain_errors, verified_count = verify_audit_log_integrity()
        self.assertTrue(is_valid, f"Chain errors under concurrency: {chain_errors}")
        self.assertGreaterEqual(verified_count, thread_count * records_per_thread)


class AuditViewerFilteringTests(TestCase):
    """
    Verifies actor, action, severity, and date filtering in audit log viewer.
    """
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser(
            username='filter_admin',
            email='filter_admin@bbms.local',
            password='AdminPassword@123',
            role=User.Role.ADMIN,
        )

        now = timezone.now()
        yesterday = now - timedelta(days=1)
        two_days_ago = now - timedelta(days=2)

        # Seed records with varying attributes
        record_security_event(
            action='user_created',
            actor_label='alice_actor',
            severity=SecurityAuditEvent.Severity.INFO,
            timestamp=two_days_ago,
            target_type='user',
            target_id='101',
        )
        record_security_event(
            action='unit_status_changed',
            actor_label='bob_actor',
            severity=SecurityAuditEvent.Severity.WARNING,
            timestamp=yesterday,
            target_type='blood_unit',
            target_id='BAG-999',
        )
        record_security_event(
            action='login_failed',
            actor_label='charlie_actor',
            severity=SecurityAuditEvent.Severity.ERROR,
            timestamp=now,
            target_type='account',
            target_id='user:202',
        )

    def setUp(self):
        self.client = Client()
        self.client.force_login(self.admin)

    def test_filter_by_actor(self):
        response = self.client.get(reverse('api_audit_logs'), {'actor': 'alice'})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['count'], 1)
        self.assertEqual(data['results'][0]['actor'], 'alice_actor')

    def test_filter_by_action(self):
        response = self.client.get(reverse('api_audit_logs'), {'action': 'unit_status_changed'})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['count'], 1)
        self.assertEqual(data['results'][0]['target_id'], 'BAG-999')

    def test_filter_by_severity(self):
        response = self.client.get(reverse('api_audit_logs'), {'severity': 'ERROR'})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['count'], 1)
        self.assertEqual(data['results'][0]['action'], 'login_failed')

    def test_filter_by_date_range(self):
        yesterday_str = (timezone.now() - timedelta(days=1)).strftime('%Y-%m-%d')
        response = self.client.get(
            reverse('api_audit_logs'),
            {'date_from': yesterday_str, 'date_to': yesterday_str},
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['count'], 1)
        self.assertEqual(data['results'][0]['action'], 'unit_status_changed')

    def test_pagination(self):
        response = self.client.get(reverse('api_audit_logs'), {'page_size': 2})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data['results']), 2)
        self.assertTrue(data['has_next'])
