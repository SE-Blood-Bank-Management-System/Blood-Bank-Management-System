from datetime import timedelta

from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from .models import BloodUnit, BloodUnitStatus


class QuarantineAndHistoryViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.staff = User.objects.create_user('queue_staff', role=User.Role.STAFF)
        cls.admin = User.objects.create_user('queue_admin', role=User.Role.ADMIN)
        cls.donor = User.objects.create_user('queue_donor')
        cls.hospital = User.objects.create_user('queue_hospital', role=User.Role.HOSPITAL)
        cls.unit = BloodUnit.objects.create(
            blood_group='O+', bag_id='QUEUE-QUARANTINED', collected_by=cls.staff,
            collection_date=timezone.now() - timedelta(days=2),
        )
        cls.discarded = BloodUnit.objects.create(blood_group='A+', bag_id='QUEUE-DISCARDED', status='Discarded')
        cls.available = BloodUnit.objects.create(blood_group='B+', bag_id='QUEUE-AVAILABLE', status='Available')
        cls.expired = BloodUnit.objects.create(
            blood_group='AB+', bag_id='QUEUE-EXPIRED', status='Available',
            expiry_date=timezone.now() - timedelta(days=1),
        )

    def setUp(self):
        self.client.force_login(self.staff)
        self.queue = reverse('inventory:quarantine')
        self.history = reverse('inventory:status_history', args=[self.unit.bag_id])

    def test_queue_lists_only_quarantined_units_with_elapsed_time(self):
        response = self.client.get(self.queue)
        self.assertContains(response, 'QUEUE-QUARANTINED')
        self.assertContains(response, '2.0 days')
        for bag in ['QUEUE-DISCARDED', 'QUEUE-AVAILABLE', 'QUEUE-EXPIRED']:
            self.assertNotContains(response, bag)
        self.assertEqual(response.context['quarantine_count'], 1)
        self.assertIn('no-store', response.headers['Cache-Control'])

    def test_queue_json_includes_current_entry_timestamp_and_unknown_blood_group(self):
        BloodUnit.objects.create(blood_group='', bag_id='QUEUE-UNKNOWN')
        data = self.client.get(reverse('api_quarantine')).json()
        self.assertEqual(data['count'], 2)
        unknown = next(unit for unit in data['units'] if unit['bag_id'] == 'QUEUE-UNKNOWN')
        self.assertIsNone(unknown['blood_group'])
        self.assertIn('quarantined_at', unknown)

    def test_history_retains_old_states_and_staff_after_unit_leaves_quarantine(self):
        self.unit.status = BloodUnitStatus.DISCARDED
        self.unit.save(actor=self.staff, status_reason='Container damaged.')
        response = self.client.get(self.history)
        for text in ['QUEUE-QUARANTINED', 'Quarantined', 'Discarded', 'queue_staff', 'Container damaged.']:
            self.assertContains(response, text)
        data = self.client.get(reverse('api_status_history', args=[self.unit.bag_id])).json()
        self.assertEqual(data['count'], 2)
        self.assertEqual(data['history'][0]['staff_id'], self.staff.pk)
        self.assertEqual(data['history'][0]['previous_status'], 'Quarantined')
        self.assertIn('timestamp', data['history'][0])
        self.assertNotContains(self.client.get(self.queue), self.unit.bag_id)

    def test_unauthorized_roles_cannot_read_html_or_api(self):
        for user in [self.donor, self.hospital]:
            self.client.force_login(user)
            for url in [self.queue, self.history, reverse('api_quarantine'),
                        reverse('api_status_history', args=[self.unit.bag_id])]:
                self.assertEqual(self.client.get(url).status_code, 403)
        self.client.logout()
        self.assertEqual(self.client.get(self.queue).status_code, 302)
        self.assertEqual(self.client.get(reverse('api_quarantine')).status_code, 401)

    def test_admin_can_read_and_all_views_reject_mutations(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(self.history).status_code, 200)
        for url in [self.queue, self.history]:
            self.assertEqual(self.client.post(url, {}).status_code, 405)

    def test_public_and_staff_availability_exclude_unsafe_and_expired_units(self):
        public = Client().get(reverse('core:public_availability'))
        counts = {row['blood_group']: row['units'] for row in public.context['inventory_summary']}
        self.assertEqual(counts['B+'], 1)
        self.assertEqual(sum(counts.values()), 1)
        dashboard = self.client.get(reverse('inventory:dashboard'))
        self.assertEqual(dashboard.context['total_units_available'], 1)
        self.assertNotContains(public, 'queue_staff')

    def test_no_available_units_returns_real_zero_counts(self):
        BloodUnit.objects.filter(pk=self.available.pk).update(expiry_date=timezone.now() - timedelta(days=1))
        response = self.client.get(reverse('core:public_availability'))
        self.assertTrue(all(row['units'] == 0 for row in response.context['inventory_summary']))

    def test_pagination_uses_total_count_and_history_remains_bounded(self):
        BloodUnit.objects.bulk_create([BloodUnit(blood_group='O+') for _ in range(26)])
        response = self.client.get(self.queue, {'page': 2})
        self.assertEqual(response.context['quarantine_count'], 27)
        self.assertEqual(len(response.context['quarantined_units']), 2)
        self.assertContains(response, 'Count: 27')

    def test_unknown_unit_history_returns_404_and_reason_is_escaped(self):
        self.assertEqual(self.client.get(reverse('inventory:status_history', args=['MISSING'])).status_code, 404)
        self.unit.status = BloodUnitStatus.DISCARDED
        self.unit.save(actor=self.staff, status_reason='<script>alert(1)</script>')
        response = self.client.get(self.history)
        self.assertContains(response, '&lt;script&gt;alert(1)&lt;/script&gt;')
        self.assertNotContains(response, '<script>alert(1)</script>')
