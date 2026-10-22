import json
from datetime import timedelta

from django.conf import settings
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from inventory.models import BloodUnit
from .models import MedicalEligibilityResponse


class DonorProfileAPITests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.donor = User.objects.create_user(
            'api_owner', email='api@example.com', phone='9876543210', address='Old street', blood_group='A+',
        )
        cls.other = User.objects.create_user('api_other', email='private@example.com')
        cls.unit = BloodUnit.objects.create(
            donor=cls.donor, blood_group='O+', bag_id='API-OWN', location='Central Blood Bank',
            collection_date=timezone.now() - timedelta(days=10), collection_notes='STAFF-SECRET',
        )
        BloodUnit.objects.create(donor=cls.other, blood_group='B+', bag_id='API-OTHER')

    def setUp(self):
        self.client.force_login(self.donor)
        self.url = reverse('donor_api:profile')

    def update(self, data, **kwargs):
        return self.client.put(self.url, json.dumps(data), content_type='application/json', **kwargs)

    def test_profile_returns_only_own_public_profile_fields(self):
        response = self.client.get(self.url, {'donor_id': self.other.pk})
        data = response.json()['profile']
        self.assertEqual(data['email'], 'api@example.com')
        self.assertEqual(set(data), {'id', 'full_name', 'email', 'date_of_birth', 'gender',
                                     'phone', 'address', 'blood_group'})
        self.assertIn('no-store', response.headers['Cache-Control'])

    def test_partial_update_preserves_omitted_fields_and_lab_group(self):
        self.assertEqual(self.update({'phone': '+91 9999999999'}).status_code, 200)
        self.donor.refresh_from_db()
        self.unit.refresh_from_db()
        self.assertEqual(self.donor.phone, '+91 9999999999')
        self.assertEqual(self.donor.address, 'Old street')
        self.assertEqual(self.donor.blood_group, 'A+')
        self.assertEqual(self.unit.blood_group, 'O+')

    def test_invalid_fields_and_privileged_updates_are_rejected(self):
        for payload in [{'phone': 'bad'}, {'blood_group': 'C+'}, {'role': 'ADMIN'},
                        {'id': self.other.pk}, {'email': 'hijacked@example.com'}, {'password': 'changed'}]:
            with self.subTest(payload=payload):
                self.assertEqual(self.update(payload).status_code, 400)
        self.donor.refresh_from_db()
        self.assertEqual(self.donor.role, User.Role.DONOR)
        self.assertEqual(self.donor.email, 'api@example.com')
        self.assertEqual(self.donor.phone, '9876543210')

    def test_malformed_json_and_wrong_types_are_rejected(self):
        self.assertEqual(self.client.put(self.url, '{bad', content_type='application/json').status_code, 400)
        for payload in [[], None, {'phone': 123}, {'address': {}}, {'blood_group': None}]:
            with self.subTest(payload=payload):
                self.assertEqual(self.update(payload).status_code, 400)
        self.assertEqual(self.client.put(self.url, 'phone=123', content_type='text/plain').status_code, 415)

    def test_api_requires_authentication_and_donor_role(self):
        self.client.logout()
        for name in ['profile', 'donations', 'eligibility']:
            self.assertEqual(self.client.get(reverse('donor_api:' + name)).status_code, 401)
        for role in [User.Role.STAFF, User.Role.HOSPITAL]:
            user = User.objects.create_user('api_' + role, role=role)
            self.client.force_login(user)
            self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_donation_json_is_private_and_excludes_staff_information(self):
        response = self.client.get(reverse('donor_api:donations'))
        data = response.json()
        self.assertEqual(data['count'], 1)
        self.assertEqual(data['donations'][0]['bag_id'], 'API-OWN')
        self.assertEqual(set(data['donations'][0]), {'bag_id', 'collection_date', 'location', 'volume_ml'})
        self.assertNotContains(response, 'API-OTHER')
        self.assertNotContains(response, 'STAFF-SECRET')

    def test_next_date_and_screening_are_distinct(self):
        MedicalEligibilityResponse.objects.create(donor=self.donor, status='Eligible')
        data = self.client.get(reverse('donor_api:eligibility')).json()
        expected = timezone.localtime(self.unit.collection_date).date() + timedelta(days=90)
        self.assertEqual(data['next_eligible_date'], expected.isoformat())
        self.assertEqual(data['medical_screening_status'], 'Eligible')
        self.assertFalse(data['can_donate_by_interval'])
        self.assertFalse(data['is_eligible'])
        self.client.force_login(self.other)
        # The other donor has a collection today and no medical screening.
        self.assertFalse(self.client.get(reverse('donor_api:eligibility')).json()['is_eligible'])

    def test_profile_put_requires_csrf_and_accepts_a_valid_token(self):
        browser = Client(enforce_csrf_checks=True)
        browser.force_login(self.donor)
        response = browser.get(self.url, secure=True)
        token = response.cookies[settings.CSRF_COOKIE_NAME].value
        data = json.dumps({'address': 'Verified street'})
        self.assertEqual(browser.put(self.url, data, content_type='application/json', secure=True).status_code, 403)
        response = browser.put(self.url, data, content_type='application/json', secure=True,
                               HTTP_X_CSRFTOKEN=token, HTTP_REFERER='https://testserver' + self.url)
        self.assertEqual(response.status_code, 200)

    def test_other_http_methods_are_not_accepted(self):
        self.assertEqual(self.client.post(self.url, {}).status_code, 405)
        self.assertEqual(self.client.delete(reverse('donor_api:donations')).status_code, 405)

    def test_empty_api_history_and_pending_screening_are_explicit(self):
        self.client.force_login(User.objects.create_user('api_first_time'))
        history = self.client.get(reverse('donor_api:donations')).json()
        self.assertEqual(history['donations'], [])
        self.assertEqual(history['count'], 0)
        eligibility = self.client.get(reverse('donor_api:eligibility')).json()
        self.assertIsNone(eligibility['next_eligible_date'])
        self.assertTrue(eligibility['can_donate_by_interval'])
        self.assertEqual(eligibility['medical_screening_status'], 'Pending Screening')
        self.assertFalse(eligibility['is_eligible'])

    def test_api_pagination_does_not_count_another_donors_records(self):
        BloodUnit.objects.bulk_create([
            BloodUnit(donor=self.donor, blood_group='A+', bag_id=f'API-PAGE-{i}',
                      collection_date=timezone.now() - timedelta(days=2)) for i in range(26)
        ])
        data = self.client.get(reverse('donor_api:donations'), {'page': 2}).json()
        self.assertEqual(data['count'], 27)
        self.assertEqual(data['page'], 2)
        self.assertEqual(len(data['donations']), 2)
