import json

from django.test import Client
from django.urls import reverse

from accounts.models import User
from requisitions.models import Requisition
from .base import RequestTestCase


class RequisitionAPITests(RequestTestCase):
    def setUp(self):
        self.client.force_login(self.hospital)
        self.url = reverse('requisition_api:list')

    def data(self, **overrides):
        return {'bloodGroup': 'O+', 'component': 'Red Blood Cells', 'quantity': 2,
                'requiredBy': self.request_data()['required_by'].isoformat(), **overrides}

    def post(self, url=None, **overrides):
        return self.client.post(url or self.url, self.data(**overrides), content_type='application/json', secure=True)

    def test_create_list_detail_and_hospital_isolation(self):
        response = self.post(isStat=True)
        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertEqual((data['status'], data['quantity'], data['remainingQuantity']), ('Pending', 2, 2))
        self.assertEqual(data['hospitalId'], self.hospital.pk)
        foreign = self.submit(actor=self.other)
        listed = self.client.get(self.url, secure=True).json()
        self.assertEqual(listed['count'], 1)
        self.assertEqual(listed['requests'][0]['requestId'], data['requestId'])
        url = reverse('requisition_api:detail', args=[data['id']])
        self.assertEqual(self.client.get(url, secure=True).json()['history'][0]['actor'], self.hospital.username)
        self.assertEqual(self.client.get(reverse('requisition_api:detail', args=[foreign.pk]), secure=True).status_code, 404)

    def test_invalid_json_types_fields_and_dates_are_400(self):
        for raw in ['{broken', '[]', 'null', '"value"']:
            response = self.client.post(self.url, raw, content_type='application/json', secure=True)
            self.assertEqual(response.status_code, 400)
        for data in [self.data(quantity=0), self.data(quantity=True), self.data(quantity='2'),
                     self.data(requiredBy='not-a-date'), self.data(requiredBy={}), self.data(requiredBy=None),
                     self.data(bloodGroup='X+'), self.data(component='Invalid'), self.data(isStat='true'),
                     self.data(hospitalId=self.other.pk), self.data(status='Fulfilled')]:
            with self.subTest(data=data):
                response = self.client.post(self.url, data, content_type='application/json', secure=True)
                self.assertEqual(response.status_code, 400)
        self.assertFalse(Requisition.objects.exists())
        self.assertEqual(self.client.post(self.url, self.request_data(), secure=True).status_code, 415)

    def test_staff_can_read_but_cannot_submit_as_a_hospital(self):
        self.submit()
        self.client.force_login(self.staff)
        self.assertEqual(self.client.get(self.url, secure=True).status_code, 200)
        self.assertEqual(self.post().status_code, 403)

    def test_review_priority_stale_version_and_no_manual_fulfilment(self):
        requisition = self.submit()
        priority_url = reverse('requisition_api:priority', args=[requisition.pk])
        response = self.client.patch(priority_url, {'isStat': True, 'version': 0},
                                     content_type='application/json', secure=True)
        self.assertEqual((response.status_code, response.json()['isStat'], response.json()['version']), (200, True, 1))
        self.client.force_login(self.staff)
        url = reverse('requisition_api:review', args=[requisition.pk])
        for data, expected in [({'action': 'approve', 'version': 0}, 409),
                               ({'action': 'reject', 'version': 1}, 400),
                               ({'action': 'fulfil', 'version': 1}, 400),
                               ({'action': 'approve', 'version': 1, 'dispatchedQuantity': 2}, 400),
                               ({'action': 'approve', 'version': True}, 400),
                               ({'action': 'approve', 'version': 1}, 200)]:
            response = self.client.post(url, data, content_type='application/json', secure=True)
            self.assertEqual(response.status_code, expected)
        self.assertEqual((response.json()['status'], response.json()['dispatchedQuantity']), ('Approved', 0))
        self.assertEqual(requisition.events.count(), 3)

    def test_priority_cannot_be_changed_by_foreign_hospital_or_after_review(self):
        requisition = self.submit(actor=self.other)
        url = reverse('requisition_api:priority', args=[requisition.pk])
        response = self.client.patch(url, {'isStat': True, 'version': 0}, content_type='application/json', secure=True)
        self.assertEqual(response.status_code, 404)
        self.client.force_login(self.other)
        for data in [{'isStat': 'yes', 'version': 0}, {'isStat': True}, {'isStat': True, 'version': False}]:
            self.assertEqual(self.client.patch(url, data, content_type='application/json', secure=True).status_code, 400)

    def test_permissions_for_anonymous_unapproved_inactive_and_flagged_donor(self):
        self.client.logout()
        self.assertEqual(self.client.get(self.url, secure=True).status_code, 401)
        self.donor.is_staff = True
        self.donor.save()
        self.client.force_login(self.donor)
        self.assertEqual(self.client.get(self.url, secure=True).status_code, 403)
        for values in [{'is_approved': False}, {'is_active': False}]:
            self.client.force_login(self.hospital)
            User.objects.filter(pk=self.hospital.pk).update(**values)
            self.assertIn(self.post().status_code, (401, 403))
            User.objects.filter(pk=self.hospital.pk).update(is_approved=True, is_active=True)
        self.assertFalse(Requisition.objects.exists())

    def test_csrf_is_enforced_on_json_create_review_and_priority(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.hospital)
        self.assertEqual(client.post(self.url, self.data(), content_type='application/json', secure=True).status_code, 403)
        client.get(reverse('requisitions:create'), secure=True)
        token = client.cookies['csrftoken'].value
        response = client.post(self.url, self.data(), content_type='application/json', secure=True,
                               HTTP_X_CSRFTOKEN=token, HTTP_ORIGIN='https://testserver')
        self.assertEqual(response.status_code, 201)
        pk = response.json()['id']
        url = reverse('requisition_api:priority', args=[pk])
        self.assertEqual(client.patch(url, {'isStat': True, 'version': 0},
                                      content_type='application/json', secure=True).status_code, 403)
        client.force_login(self.staff)
        url = reverse('requisition_api:review', args=[pk])
        self.assertEqual(client.post(url, {'action': 'approve', 'version': 0},
                                     content_type='application/json', secure=True).status_code, 403)

    def test_unknown_status_or_wrong_method_never_changes_data(self):
        requisition = self.submit()
        self.assertEqual(self.client.get(self.url + '?status=Invalid', secure=True).status_code, 400)
        url = reverse('requisition_api:priority', args=[requisition.pk])
        self.assertEqual(self.client.get(url, secure=True).status_code, 405)
        self.assertEqual(self.client.delete(self.url, secure=True).status_code, 405)
        requisition.refresh_from_db()
        self.assertFalse(requisition.is_stat)
