import json
from django.test import TestCase, Client
from django.urls import reverse
from accounts.models import User
from donors.models import MedicalEligibilityResponse, is_eligible


class DonorViewTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username='donor_test',
            password='testpassword',
            role=User.Role.DONOR
        )
        self.eligible_data = {
            'feeling_well': 'yes',
            'recent_fever': 'no',
            'antibiotics': 'no',
            'tattoo_piercing': 'no',
            'malaria_travel': 'no',
            'pregnancy': 'no',
            'chronic_blood_conditions': 'no',
        }

    def test_donor_views_require_login(self):
        dashboard_res = self.client.get(reverse('donors:dashboard'))
        self.assertEqual(dashboard_res.status_code, 302)

        history_res = self.client.get(reverse('donors:history'))
        self.assertEqual(history_res.status_code, 302)

        eligibility_res = self.client.get(reverse('donors:eligibility'))
        self.assertEqual(eligibility_res.status_code, 302)

    def test_unauthenticated_submission_rejection(self):
        # Security: unauthenticated access to questionnaire submission is denied
        post_res = self.client.post(reverse('donors:eligibility'), self.eligible_data)
        self.assertEqual(post_res.status_code, 302)
        self.assertEqual(MedicalEligibilityResponse.objects.count(), 0)

        # Unauthenticated JSON API request
        json_res = self.client.post(
            reverse('donors:eligibility'),
            data=json.dumps(self.eligible_data),
            content_type='application/json'
        )
        self.assertEqual(json_res.status_code, 401)
        self.assertEqual(MedicalEligibilityResponse.objects.count(), 0)

    def test_donor_views_authenticated(self):
        self.client.login(username='donor_test', password='testpassword')
        dashboard_res = self.client.get(reverse('donors:dashboard'))
        self.assertEqual(dashboard_res.status_code, 200)
        self.assertTemplateUsed(dashboard_res, 'donors/dashboard.html')

        eligibility_res = self.client.get(reverse('donors:eligibility'))
        self.assertEqual(eligibility_res.status_code, 200)
        self.assertTemplateUsed(eligibility_res, 'donors/eligibility.html')

    def test_donor_views_reject_unauthorized_roles(self):
        hospital_user = User.objects.create_user(
            username='hospital_intruder',
            password='testpassword',
            role=User.Role.HOSPITAL,
            is_approved=True
        )
        self.client.login(username=hospital_user.username, password='testpassword')
        dashboard_res = self.client.get(reverse('donors:dashboard'))
        self.assertEqual(dashboard_res.status_code, 403)

        eligibility_res = self.client.get(reverse('donors:eligibility'))
        self.assertEqual(eligibility_res.status_code, 403)

        staff_user = User.objects.create_user(
            username='staff_intruder',
            password='testpassword',
            role=User.Role.STAFF
        )
        self.client.login(username=staff_user.username, password='testpassword')
        self.assertEqual(self.client.get(reverse('donors:eligibility')).status_code, 403)

    def test_eligible_submission_marks_donor_eligible(self):
        # Eligible response set -> 'Eligible'
        self.client.login(username='donor_test', password='testpassword')
        self.assertFalse(self.user.is_eligible)

        res = self.client.post(reverse('donors:eligibility'), self.eligible_data)
        self.assertEqual(res.status_code, 200)
        self.assertTemplateUsed(res, 'donors/eligibility.html')
        self.assertEqual(res.context['status'], 'Eligible')
        self.assertTrue(res.context['is_eligible'])

        # Persisted audit record check
        self.assertEqual(MedicalEligibilityResponse.objects.filter(donor=self.user).count(), 1)
        record = MedicalEligibilityResponse.objects.filter(donor=self.user).first()
        self.assertEqual(record.status, MedicalEligibilityResponse.Status.ELIGIBLE)
        self.assertTrue(record.is_eligible)
        self.assertEqual(record.ineligibility_reason, '')
        self.assertIn('feeling_well', record.responses)

        # User helper property & function check
        self.user.refresh_from_db()
        self.assertTrue(self.user.is_eligible)
        self.assertTrue(is_eligible(self.user))

        # Check UI confirmation
        content = res.content.decode()
        self.assertIn('Eligible to Donate Blood', content)
        self.assertIn(reverse('appointments:book'), content)

    def test_disqualifying_submission_marks_donor_ineligible_with_reason(self):
        # Ineligible response set -> 'Ineligible' with reason
        self.client.login(username='donor_test', password='testpassword')
        ineligible_data = self.eligible_data.copy()
        ineligible_data['recent_fever'] = 'yes'

        res = self.client.post(reverse('donors:eligibility'), ineligible_data)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.context['status'], 'Ineligible')
        self.assertFalse(res.context['is_eligible'])

        # Persisted audit record check
        self.assertEqual(MedicalEligibilityResponse.objects.filter(donor=self.user).count(), 1)
        record = MedicalEligibilityResponse.objects.filter(donor=self.user).first()
        self.assertEqual(record.status, MedicalEligibilityResponse.Status.INELIGIBLE)
        self.assertFalse(record.is_eligible)
        self.assertIn('Recent fever or illness', record.ineligibility_reason)

        # User helper property & function check
        self.user.refresh_from_db()
        self.assertFalse(self.user.is_eligible)
        self.assertFalse(is_eligible(self.user))

        # Check respectful on-screen explanation
        content = res.content.decode()
        self.assertIn('Temporarily Ineligible to Donate', content)
        self.assertIn('Recent fever or illness in the last 48 hours.', content)

    def test_multiple_disqualifying_conditions_listed(self):
        self.client.login(username='donor_test', password='testpassword')
        multi_disqualify = self.eligible_data.copy()
        multi_disqualify['antibiotics'] = 'yes'
        multi_disqualify['tattoo_piercing'] = 'yes'

        res = self.client.post(reverse('donors:eligibility'), multi_disqualify)
        self.assertEqual(res.status_code, 200)

        record = MedicalEligibilityResponse.objects.filter(donor=self.user).first()
        self.assertEqual(record.status, 'Ineligible')
        self.assertIn('Antibiotics taken within the past 7 days', record.ineligibility_reason)
        self.assertIn('Tattoo or piercing received in the last 6 months', record.ineligibility_reason)

        content = res.content.decode()
        self.assertIn('Antibiotics taken within the past 7 days', content)
        self.assertIn('Tattoo or piercing received in the last 6 months', content)

    def test_form_validation_missing_required_answers_rejected(self):
        # Form validation: missing required answers are rejected
        self.client.login(username='donor_test', password='testpassword')

        # Empty submission
        res = self.client.post(reverse('donors:eligibility'), {})
        self.assertEqual(res.status_code, 200)
        self.assertFalse(res.context['form'].is_valid())
        self.assertEqual(MedicalEligibilityResponse.objects.count(), 0)

        # Partial submission
        partial_data = {'feeling_well': 'yes', 'recent_fever': 'no'}
        res = self.client.post(reverse('donors:eligibility'), partial_data)
        self.assertEqual(res.status_code, 200)
        self.assertFalse(res.context['form'].is_valid())
        self.assertIn('antibiotics', res.context['form'].errors)
        self.assertEqual(MedicalEligibilityResponse.objects.count(), 0)

    def test_api_json_eligibility_submission_and_query(self):
        self.client.login(username='donor_test', password='testpassword')

        # API eligible submission
        res = self.client.post(
            reverse('donors:eligibility'),
            data=json.dumps(self.eligible_data),
            content_type='application/json'
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data['status'], 'Eligible')
        self.assertTrue(data['is_eligible'])

        # API GET status query
        get_res = self.client.get(
            reverse('donors:eligibility'),
            HTTP_ACCEPT='application/json'
        )
        self.assertEqual(get_res.status_code, 200)
        query_data = get_res.json()
        self.assertTrue(query_data['is_eligible'])
        self.assertEqual(query_data['status'], 'Eligible')

    def test_booking_integration_with_eligibility(self):
        self.client.login(username='donor_test', password='testpassword')

        # Before screening, donor is not eligible
        self.assertFalse(self.user.is_eligible)
        book_res = self.client.get(reverse('appointments:book'))
        self.assertEqual(book_res.status_code, 200)
        self.assertFalse(book_res.context['is_eligible'])
        self.assertIn('Medical Eligibility Pre-Screening Required', book_res.content.decode())

        # After passing screening
        self.client.post(reverse('donors:eligibility'), self.eligible_data)
        self.user.refresh_from_db()
        self.assertTrue(self.user.is_eligible)

        book_res_after = self.client.get(reverse('appointments:book'))
        self.assertEqual(book_res_after.status_code, 200)
        self.assertTrue(book_res_after.context['is_eligible'])
