from datetime import date, timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from inventory.models import BloodUnit, ComponentType


class DonorProfileViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.donor = User.objects.create_user(
            'profile_owner', first_name='Jane', last_name='Donor', email='owner@example.com',
            phone='9876543210', date_of_birth=date(1995, 5, 15), gender='Female', blood_group='A+',
        )
        cls.other = User.objects.create_user('private_other', email='private@example.com')
        cls.staff = User.objects.create_user('profile_staff', role=User.Role.STAFF)
        cls.hospital = User.objects.create_user('profile_hospital', role=User.Role.HOSPITAL)
        cls.admin = User.objects.create_user('profile_admin', role=User.Role.ADMIN)
        cls.older = BloodUnit.objects.create(
            donor=cls.donor, blood_group='O+', bag_id='OWN-OLDER', location='Central Blood Bank',
            collection_date=timezone.now() - timedelta(days=100),
        )
        cls.recent = BloodUnit.objects.create(
            donor=cls.donor, blood_group='O+', bag_id='OWN-RECENT', location='Metro Blood Center',
            collection_date=timezone.now() - timedelta(days=10), collection_notes='STAFF-ONLY-NOTE',
        )
        BloodUnit.objects.create(donor=cls.other, blood_group='B+', bag_id='OTHER-SECRET')
        BloodUnit.objects.create(
            donor=cls.donor, blood_group='O+', parent_unit=cls.recent,
            component_type=ComponentType.RBC, bag_id='COMPONENT-SECRET',
        )

    def setUp(self):
        self.client.force_login(self.donor)

    def test_own_profile_displays_registered_fields_and_next_date(self):
        response = self.client.get(reverse('accounts:profile'))
        self.assertContains(response, '<option value="B+">B+</option>', html=True)
        for text in ['Jane Donor', 'owner@example.com', '9876543210', 'Female', 'A+']:
            self.assertContains(response, text)
        expected = timezone.localtime(self.recent.collection_date).date() + timedelta(days=90)
        self.assertEqual(response.context['next_eligible_date'], expected)
        self.assertContains(response, expected.strftime('%d %b %Y'))
        self.assertIn('no-store', response.headers['Cache-Control'])

    def test_updates_only_permitted_fields_and_not_laboratory_group(self):
        response = self.client.post(reverse('accounts:profile'), {
            'phone': '+91 9999999999', 'address': 'Updated street', 'blood_group': 'AB+',
            'role': 'ADMIN', 'email': 'hijacked@example.com', 'id': self.other.pk,
        })
        self.assertRedirects(response, reverse('accounts:profile'))
        self.donor.refresh_from_db()
        self.recent.refresh_from_db()
        self.assertEqual((self.donor.phone, self.donor.address, self.donor.blood_group),
                         ('+91 9999999999', 'Updated street', 'AB+'))
        self.assertEqual(self.donor.role, User.Role.DONOR)
        self.assertEqual(self.donor.email, 'owner@example.com')
        self.assertEqual(self.recent.blood_group, 'O+')

    def test_invalid_updates_show_errors_and_preserve_values_without_saving(self):
        response = self.client.post(reverse('accounts:profile'), {
            'phone': '+91 9999999999', 'address': 'New street', 'blood_group': 'C+',
        })
        self.assertIn('blood_group', response.context['form'].errors)
        self.assertContains(response, 'id="id_blood_group_error"')
        self.assertContains(response, 'value="+91 9999999999"')
        self.donor.refresh_from_db()
        self.assertEqual(self.donor.phone, '9876543210')
        response = self.client.post(reverse('accounts:profile'), {'phone': 'not-a-phone'})
        self.assertIn('phone', response.context['form'].errors)

    def test_history_is_private_ordered_and_contains_collection_details(self):
        response = self.client.get(reverse('donors:history'))
        for text in ['OWN-RECENT', 'OWN-OLDER', 'Metro Blood Center', '450 mL']:
            self.assertContains(response, text)
        for text in ['OTHER-SECRET', 'COMPONENT-SECRET', 'STAFF-ONLY-NOTE']:
            self.assertNotContains(response, text)
        self.assertLess(response.content.index(b'OWN-RECENT'), response.content.index(b'OWN-OLDER'))

    def test_dashboard_displays_real_counts_and_recent_donations(self):
        response = self.client.get(reverse('donors:dashboard'))
        self.assertEqual(response.context['total_donations'], 2)
        self.assertEqual(list(response.context['recent_donations']), [self.recent, self.older])
        self.assertContains(response, 'OWN-RECENT')

    def test_donor_cannot_select_another_donor_or_discover_missing_accounts(self):
        for target in [self.other.pk, 999999]:
            for name in ['donors:profile', 'donors:donor_history']:
                self.assertEqual(self.client.get(reverse(name, args=[target])).status_code, 403)
        response = self.client.get(reverse('accounts:profile'), {'donor_id': self.other.pk})
        self.assertContains(response, 'owner@example.com')
        self.assertNotContains(response, 'private@example.com')

    def test_staff_and_admin_can_review_donor_details_but_cannot_edit_them(self):
        for user in [self.staff, self.admin]:
            self.client.force_login(user)
            url = reverse('donors:profile', args=[self.donor.pk])
            self.assertContains(self.client.get(url), 'owner@example.com')
            self.assertEqual(self.client.post(url, {'phone': '1111111111'}).status_code, 405)
            history = self.client.get(reverse('donors:donor_history', args=[self.donor.pk]))
            self.assertContains(history, 'OWN-RECENT')
            self.assertNotContains(history, 'OTHER-SECRET')

    def test_staff_missing_donor_is_404_and_hospital_access_is_forbidden(self):
        self.client.force_login(self.staff)
        self.assertEqual(self.client.get(reverse('donors:profile', args=[999999])).status_code, 404)
        self.client.force_login(self.hospital)
        self.assertEqual(self.client.get(reverse('donors:profile', args=[self.donor.pk])).status_code, 403)

    def test_empty_history_and_unauthenticated_access(self):
        new_donor = User.objects.create_user('first_time_donor')
        self.client.force_login(new_donor)
        self.assertContains(self.client.get(reverse('donors:history')), 'No donation records found yet')
        self.client.logout()
        for url in [reverse('accounts:profile'), reverse('donors:history'),
                    reverse('donors:profile', args=[self.donor.pk])]:
            self.assertEqual(self.client.get(url).status_code, 302)

    def test_history_is_paginated(self):
        BloodUnit.objects.bulk_create([
            BloodUnit(donor=self.donor, blood_group='A+', bag_id=f'PAGE-{i}',
                      collection_date=timezone.now() - timedelta(days=2)) for i in range(26)
        ])
        response = self.client.get(reverse('donors:history'), {'page': 2})
        self.assertEqual(len(response.context['donations']), 3)
        self.assertContains(response, 'Page 2 of 2')

    def test_profile_renders_stored_markup_as_text(self):
        self.donor.address = '<script>alert(1)</script>'
        self.donor.save()
        response = self.client.get(reverse('accounts:profile'))
        self.assertContains(response, '&lt;script&gt;alert(1)&lt;/script&gt;')
        self.assertNotContains(response, '<script>alert(1)</script>')
