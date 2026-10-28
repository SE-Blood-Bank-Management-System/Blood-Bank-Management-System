from datetime import timedelta

from django.test import Client
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from requisitions.models import Requisition
from requisitions.services import review_requisition
from .base import RequestTestCase


class RequisitionViewTests(RequestTestCase):
    def setUp(self):
        self.client.force_login(self.hospital)

    def test_hospital_submits_tracks_and_updates_priority(self):
        response = self.client.post(reverse('requisitions:create'), {
            **self.request_data(), 'hospital': self.other.pk, 'status': 'Fulfilled', 'is_stat': True,
        }, secure=True)
        requisition = Requisition.objects.get()
        self.assertRedirects(response, reverse('requisitions:detail', args=[requisition.pk]))
        self.assertEqual((requisition.hospital_id, requisition.status, requisition.is_stat),
                         (self.hospital.pk, 'Pending', True))
        response = self.client.get(response.url, secure=True)
        self.assertContains(response, 'Emergency / STAT')
        self.assertContains(response, 'Request history')
        self.assertNotContains(response, 'Staff review')
        response = self.client.post(
            reverse('requisitions:priority', args=[requisition.pk]), {'version': 0}, secure=True,
        )
        self.assertRedirects(response, reverse('requisitions:detail', args=[requisition.pk]))
        requisition.refresh_from_db()
        self.assertFalse(requisition.is_stat)

    def test_invalid_submission_and_blood_group_labels(self):
        response = self.client.get(reverse('requisitions:create'), secure=True)
        choices = dict(response.context['form'].fields['blood_group'].choices)
        self.assertEqual(choices['B+'], 'B+')
        for data in [self.request_data(quantity=0),
                     self.request_data(required_by=timezone.localdate() - timedelta(days=1))]:
            response = self.client.post(reverse('requisitions:create'), data, secure=True)
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.context['form'].errors)
        self.assertFalse(Requisition.objects.exists())

    def test_hospital_cannot_see_another_hospital_request_or_review_it(self):
        foreign = self.submit(actor=self.other)
        response = self.client.get(reverse('requisitions:list'), secure=True)
        self.assertNotContains(response, foreign.requisition_id)
        for name in ['detail', 'priority']:
            url = reverse('requisitions:' + name, args=[foreign.pk])
            response = (self.client.get(url, secure=True) if name == 'detail' else
                        self.client.post(url, {'version': 0, 'is_stat': True}, secure=True))
            self.assertEqual(response.status_code, 404)
        response = self.client.post(reverse('requisitions:review', args=[foreign.pk]),
                                    {'action': 'approve', 'version': 0}, secure=True)
        self.assertEqual(response.status_code, 403)

    def test_staff_queue_review_and_reason_display(self):
        ordinary, urgent = self.submit(), self.submit(actor=self.other, is_stat=True)
        self.client.force_login(self.staff)
        response = self.client.get(reverse('requisitions:list'), secure=True)
        self.assertLess(response.content.index(urgent.requisition_id.encode()),
                        response.content.index(ordinary.requisition_id.encode()))
        self.assertContains(response, 'requisition-alerts.js')
        url = reverse('requisitions:review', args=[urgent.pk])
        invalid = self.client.post(url, {'action': 'reject', 'version': 0}, secure=True)
        self.assertEqual(invalid.status_code, 400)
        self.assertContains(invalid, 'A rejection reason is required.', status_code=400)
        response = self.client.post(
            url, {'action': 'reject', 'reason': '<script>No stock</script>', 'version': 0}, secure=True,
        )
        self.assertEqual(response.status_code, 302)
        self.client.force_login(self.other)
        response = self.client.get(reverse('requisitions:detail', args=[urgent.pk]), secure=True)
        self.assertContains(response, '&lt;script&gt;No stock&lt;/script&gt;')
        self.assertNotContains(response, '<script>No stock</script>')
        self.assertContains(response, self.staff.username)

    def test_stale_or_repeated_review_returns_visible_conflict(self):
        requisition = self.submit()
        self.client.force_login(self.staff)
        review_requisition(requisition.pk, actor=self.staff, action='approve')
        response = self.client.post(reverse('requisitions:review', args=[requisition.pk]),
                                    {'action': 'approve', 'version': 0}, secure=True)
        self.assertContains(response, 'Only a Pending requisition can be reviewed.', status_code=409)
        self.assertEqual(requisition.events.count(), 2)

    def test_role_denials_include_donor_with_django_staff_flag(self):
        self.donor.is_staff = True
        self.donor.save()
        self.client.force_login(self.donor)
        for name in ['list', 'create', 'stat_alerts']:
            self.assertEqual(self.client.get(reverse('requisitions:' + name), secure=True).status_code, 403)
        self.client.force_login(self.hospital)
        self.assertEqual(self.client.get(reverse('requisitions:stat_alerts'), secure=True).status_code, 403)
        self.client.logout()
        self.assertEqual(self.client.get(reverse('requisitions:list'), secure=True).status_code, 302)

    def test_unapproved_or_inactive_hospital_cannot_submit(self):
        for values in [{'is_approved': False}, {'is_active': False}]:
            User.objects.filter(pk=self.hospital.pk).update(**values)
            response = self.client.post(reverse('requisitions:create'), self.request_data(), secure=True)
            self.assertIn(response.status_code, (302, 403))
            self.assertFalse(Requisition.objects.exists())
            User.objects.filter(pk=self.hospital.pk).update(is_approved=True, is_active=True)
            self.client.force_login(self.hospital)

    def test_live_alerts_include_new_stat_without_reloading_the_page(self):
        self.client.force_login(self.staff)
        url = reverse('requisitions:stat_alerts')
        self.assertEqual(self.client.get(url, secure=True).json()['count'], 0)
        urgent = self.submit(is_stat=True)
        response = self.client.get(url, secure=True)
        self.assertEqual((response.json()['count'], response.json()['latest_id']), (1, urgent.requisition_id))
        self.assertIn('no-store', response['Cache-Control'])
        review_requisition(urgent.pk, actor=self.staff, action='approve')
        self.assertEqual(self.client.get(url, secure=True).json()['count'], 0)

    def test_csrf_required_for_html_submission_and_priority(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.hospital)
        url = reverse('requisitions:create')
        self.assertEqual(client.post(url, self.request_data(), secure=True).status_code, 403)
        client.get(url, secure=True)
        token = client.cookies['csrftoken'].value
        response = client.post(
            url, self.request_data(), HTTP_X_CSRFTOKEN=token, HTTP_ORIGIN='https://testserver', secure=True,
        )
        self.assertEqual(response.status_code, 302)
        requisition = Requisition.objects.get()
        self.assertEqual(client.post(reverse('requisitions:priority', args=[requisition.pk]),
                                     {'version': 0, 'is_stat': True}, secure=True).status_code, 403)

    def test_filters_pagination_and_gets_cannot_mutate(self):
        for _ in range(26):
            self.submit()
        self.assertEqual(len(self.client.get(reverse('requisitions:list'), secure=True).context['page']), 25)
        self.assertEqual(len(self.client.get(reverse('requisitions:list') + '?page=2', secure=True).context['page']), 1)
        self.assertEqual(self.client.get(reverse('requisitions:list') + '?status=unknown', secure=True).status_code, 400)
        requisition = Requisition.objects.first()
        response = self.client.get(reverse('requisitions:priority', args=[requisition.pk]), secure=True)
        self.assertEqual(response.status_code, 405)
        self.client.force_login(self.staff)
        self.assertEqual(self.client.get(reverse('requisitions:review', args=[requisition.pk]), secure=True).status_code, 405)

    def test_admin_records_cannot_bypass_review(self):
        administrator = User.objects.create_superuser('requisition_admin', email='req-admin@example.com')
        self.client.force_login(administrator)
        requisition = self.submit()
        self.assertEqual(self.client.get(reverse('admin:requisitions_requisition_changelist'), secure=True).status_code, 200)
        response = self.client.post(
            reverse('admin:requisitions_requisition_change', args=[requisition.pk]), {'status': 'Fulfilled'}, secure=True,
        )
        self.assertEqual(response.status_code, 403)
