"""
Comprehensive tests for blood group management, unit lifecycle, and RBAC guards.
SRS References:
- Section 4.6 (BBMS-F-020, BBMS-F-021): Unique Blood Unit / Bag ID
- Section 4.7 (BBMS-F-022, BBMS-F-023): Blood Group Management (TC-BAG-02)
- Section 4.8, 4.9 (BBMS-F-026, BBMS-F-028, BBMS-F-030): Quarantine & Testing
- Section 4.11 (BBMS-F-033, BBMS-F-034): Blood Inventory Management
- Section 5.1.2 (BBMS-SR-001, BBMS-SR-003): Security & RBAC Enforcement
"""
import json
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError
from django.test import Client, TestCase
from django.urls import reverse

from accounts.models import User
from core.constants import BloodGroup, VALID_BLOOD_GROUPS
from inventory.forms import BloodGroupCorrectionForm
from inventory.models import BloodUnit, BloodUnitStatus, ComponentType


class BloodUnitModelTests(TestCase):
    """
    Unit tests for BloodUnit model:
    - 8 valid ABO/Rh blood groups (BBMS-F-022)
    - Rejection of invalid blood group values
    - Separation of donor self-reported and unit lab-confirmed blood groups (BBMS-F-023, TC-BAG-02)
    - Bag ID automatic generation and uniqueness (BBMS-F-020, BBMS-F-021, TC-BAG-01)
    - Lifecycle defaults (BBMS-F-026)
    """
    def setUp(self):
        self.donor = User.objects.create_user(
            username='donor_test',
            email='donor_test@example.com',
            password='password123',
            role=User.Role.DONOR,
            blood_group=BloodGroup.A_POS
        )
        self.staff_user = User.objects.create_user(
            username='staff_test',
            email='staff_test@example.com',
            password='password123',
            role=User.Role.STAFF
        )
        self.admin_user = User.objects.create_superuser(
            username='admin_test',
            email='admin_test@example.com',
            password='password123'
        )
        self.hospital_user = User.objects.create_user(
            username='hosp_test',
            email='hosp_test@example.com',
            password='password123',
            role=User.Role.HOSPITAL,
            is_approved=True
        )

    def test_all_eight_blood_groups_supported_on_unit(self):
        """Verify all eight standard ABO/Rh blood groups are valid on blood unit (BBMS-F-022)."""
        for bg in VALID_BLOOD_GROUPS:
            unit = BloodUnit.objects.create(
                blood_group=bg,
                volume_ml=450,
                status=BloodUnitStatus.QUARANTINED
            )
            self.assertTrue(unit.bag_id.startswith('BAG-'))
            fetched = BloodUnit.objects.get(id=unit.id)
            self.assertEqual(fetched.blood_group, bg)

    def test_rejection_of_invalid_blood_group_on_model(self):
        """Verify invalid blood group values fail validation."""
        for invalid in ['C+', 'Z-', 'INVALID', '123', 'A++', 'O*']:
            unit = BloodUnit(blood_group=invalid, volume_ml=450)
            with self.assertRaises(ValidationError):
                unit.full_clean()

    def test_automatic_unique_bag_id_generation(self):
        """Verify each blood unit gets an automatic unique Bag ID (BBMS-F-020)."""
        u1 = BloodUnit.objects.create(blood_group=BloodGroup.O_POS)
        u2 = BloodUnit.objects.create(blood_group=BloodGroup.O_NEG)
        self.assertIsNotNone(u1.bag_id)
        self.assertIsNotNone(u2.bag_id)
        self.assertNotEqual(u1.bag_id, u2.bag_id)
        self.assertTrue(u1.bag_id.startswith('BAG-'))

    def test_duplicate_bag_id_rejected(self):
        """Verify duplicate Bag ID creation is prevented by database unique constraint (BBMS-F-021)."""
        BloodUnit.objects.create(bag_id='BAG-FIXED-001', blood_group=BloodGroup.A_POS)
        with self.assertRaises(IntegrityError):
            BloodUnit.objects.create(bag_id='BAG-FIXED-001', blood_group=BloodGroup.B_POS)

    def test_default_status_is_quarantined(self):
        """Verify newly created unit defaults to Quarantined status (BBMS-F-026)."""
        unit = BloodUnit.objects.create(blood_group=BloodGroup.B_POS)
        self.assertEqual(unit.status, BloodUnitStatus.QUARANTINED)
        self.assertTrue(unit.is_quarantined)
        self.assertFalse(unit.is_available)

    def test_component_shelf_life_calculation(self):
        """Verify default expiry dates for each component type (BBMS-F-037)."""
        wb = BloodUnit.objects.create(blood_group=BloodGroup.A_POS, component_type=ComponentType.WHOLE_BLOOD)
        plt = BloodUnit.objects.create(blood_group=BloodGroup.A_POS, component_type=ComponentType.PLATELETS)
        ffp = BloodUnit.objects.create(blood_group=BloodGroup.A_POS, component_type=ComponentType.PLASMA)

        # Whole blood ~42 days, Platelets ~5 days, Plasma ~365 days
        self.assertEqual((wb.expiry_date.date() - wb.collection_date.date()).days, 42)
        self.assertEqual((plt.expiry_date.date() - plt.collection_date.date()).days, 5)
        self.assertEqual((ffp.expiry_date.date() - ffp.collection_date.date()).days, 365)

    def test_donor_self_reported_vs_lab_confirmed_separation(self):
        """
        Verify donor self-reported blood group is stored separately from unit lab-confirmed
        blood group (SRS BBMS-F-023, TC-BAG-02).
        Updating unit does not change donor, and updating donor does not change unit.
        """
        self.assertEqual(self.donor.blood_group, BloodGroup.A_POS)

        # Create unit collected from donor with initial matching group
        unit = BloodUnit.objects.create(
            donor=self.donor,
            blood_group=BloodGroup.A_POS,
            volume_ml=450
        )
        self.assertEqual(unit.donor_self_reported_group, BloodGroup.A_POS)
        self.assertEqual(unit.blood_group, BloodGroup.A_POS)

        # Staff performs serology typing and corrects unit to A-
        unit.update_blood_group(
            BloodGroup.A_NEG,
            staff_user=self.staff_user,
            notes='Laboratory serology typing confirmed Rh negative.'
        )

        # Unit blood group is updated and staff audit is recorded
        self.assertEqual(unit.blood_group, BloodGroup.A_NEG)
        self.assertEqual(unit.lab_confirmed_by, self.staff_user)
        self.assertIsNotNone(unit.lab_confirmed_at)
        self.assertIn('Rh negative', unit.blood_group_notes)

        # Donor's self-reported profile blood group remains untouched!
        self.donor.refresh_from_db()
        self.assertEqual(self.donor.blood_group, BloodGroup.A_POS)
        self.assertEqual(unit.donor_self_reported_group, BloodGroup.A_POS)

        # Donor updates self-reported blood group on profile
        self.donor.blood_group = BloodGroup.B_POS
        self.donor.save()

        # Blood unit's lab-confirmed blood group remains unchanged
        unit.refresh_from_db()
        self.assertEqual(unit.blood_group, BloodGroup.A_NEG)
        self.assertEqual(unit.donor_self_reported_group, BloodGroup.B_POS)

    def test_unauthorized_user_cannot_update_blood_group(self):
        """Verify non-staff users (donor, hospital) cannot modify blood group on model (BBMS-SR-003)."""
        unit = BloodUnit.objects.create(blood_group=BloodGroup.O_POS)

        # Donor attempt
        with self.assertRaises(PermissionDenied):
            unit.update_blood_group(BloodGroup.O_NEG, staff_user=self.donor)

        # Hospital attempt
        with self.assertRaises(PermissionDenied):
            unit.update_blood_group(BloodGroup.O_NEG, staff_user=self.hospital_user)

        # Unit remains unchanged
        unit.refresh_from_db()
        self.assertEqual(unit.blood_group, BloodGroup.O_POS)

    def test_authorized_staff_and_admin_can_update_blood_group(self):
        """Verify staff and administrator can successfully record/correct blood group."""
        unit = BloodUnit.objects.create(blood_group=BloodGroup.O_POS)

        # Staff update
        unit.update_blood_group(BloodGroup.O_NEG, staff_user=self.staff_user, notes='Staff confirmation')
        self.assertEqual(unit.blood_group, BloodGroup.O_NEG)
        self.assertEqual(unit.lab_confirmed_by, self.staff_user)

        # Admin update
        unit.update_blood_group(BloodGroup.AB_POS, staff_user=self.admin_user, notes='Admin correction')
        self.assertEqual(unit.blood_group, BloodGroup.AB_POS)
        self.assertEqual(unit.lab_confirmed_by, self.admin_user)

    def test_update_blood_group_rejects_invalid_values(self):
        """Verify update_blood_group rejects invalid blood groups."""
        unit = BloodUnit.objects.create(blood_group=BloodGroup.A_POS)
        for invalid in ['C+', '', None, 'XYZ']:
            with self.assertRaises(ValidationError):
                unit.update_blood_group(invalid, staff_user=self.staff_user)


class BloodGroupCorrectionFormTests(TestCase):
    """
    Tests for BloodGroupCorrectionForm:
    - Validates all 8 ABO/Rh blood groups
    - Rejects invalid values
    """
    def test_form_accepts_all_eight_valid_groups(self):
        for bg in VALID_BLOOD_GROUPS:
            form = BloodGroupCorrectionForm(data={
                'blood_group': bg,
                'notes': f'Testing {bg}'
            })
            self.assertTrue(form.is_valid(), f"Form should be valid for {bg}: {form.errors}")
            self.assertEqual(form.cleaned_data['blood_group'], bg)

    def test_form_rejects_invalid_values(self):
        for invalid in ['C+', 'INVALID', '', '123']:
            form = BloodGroupCorrectionForm(data={'blood_group': invalid})
            self.assertFalse(form.is_valid())
            self.assertIn('blood_group', form.errors)


class BloodGroupViewsAndSecurityTests(TestCase):
    """
    Integration tests for blood group views, RBAC guards, and REST API.
    SRS: 4.7 (BBMS-F-022, BBMS-F-023), 5.1.2 (BBMS-SR-001, BBMS-SR-003).
    """
    def setUp(self):
        self.client = Client()
        self.donor = User.objects.create_user(
            username='donor_v',
            email='donor_v@example.com',
            password='password123',
            role=User.Role.DONOR,
            blood_group=BloodGroup.A_POS
        )
        self.hospital = User.objects.create_user(
            username='hosp_v',
            email='hosp_v@example.com',
            password='password123',
            role=User.Role.HOSPITAL,
            is_approved=True
        )
        self.staff = User.objects.create_user(
            username='staff_v',
            email='staff_v@example.com',
            password='password123',
            role=User.Role.STAFF
        )
        self.admin = User.objects.create_superuser(
            username='admin_v',
            email='admin_v@example.com',
            password='password123'
        )
        self.unit = BloodUnit.objects.create(
            donor=self.donor,
            blood_group=BloodGroup.A_POS,
            volume_ml=450,
            status=BloodUnitStatus.QUARANTINED
        )

    def test_unit_detail_access_controls(self):
        """Unauthenticated redirected to login; donor/hospital get 403; staff/admin get 200."""
        detail_url = reverse('inventory:unit_detail', kwargs={'bag_id': self.unit.bag_id})

        # Unauthenticated
        res = self.client.get(detail_url)
        self.assertEqual(res.status_code, 302)

        # Donor
        self.client.login(username=self.donor.username, password='password123')
        res = self.client.get(detail_url)
        self.assertEqual(res.status_code, 403)

        # Hospital
        self.client.login(username=self.hospital.username, password='password123')
        res = self.client.get(detail_url)
        self.assertEqual(res.status_code, 403)

        # Staff
        self.client.login(username=self.staff.username, password='password123')
        res = self.client.get(detail_url)
        self.assertEqual(res.status_code, 200)
        self.assertTemplateUsed(res, 'inventory/unit_detail.html')
        self.assertContains(res, self.unit.bag_id)
        self.assertContains(res, 'Donor Profile vs. Unit Record')

        # Admin
        self.client.login(username=self.admin.username, password='password123')
        res = self.client.get(detail_url)
        self.assertEqual(res.status_code, 200)

    def test_unit_detail_displays_separate_donor_and_lab_blood_groups(self):
        """Verify template renders donor self-reported and unit lab-confirmed blood groups."""
        # Change unit to A- while donor stays A+
        self.unit.blood_group = BloodGroup.A_NEG
        self.unit.save()

        self.client.login(username=self.staff.username, password='password123')
        detail_url = reverse('inventory:unit_detail', kwargs={'bag_id': self.unit.bag_id})
        res = self.client.get(detail_url)

        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'Donor Self-Reported Group')
        self.assertContains(res, 'Lab-Confirmed Unit Group')
        self.assertContains(res, BloodGroup.A_POS)
        self.assertContains(res, BloodGroup.A_NEG)

    def test_update_unit_blood_group_form_post_by_staff(self):
        """Authorized staff can update unit blood group via HTML form POST."""
        self.client.login(username=self.staff.username, password='password123')
        post_url = reverse('inventory:update_blood_group', kwargs={'bag_id': self.unit.bag_id})

        res = self.client.post(post_url, {
            'blood_group': BloodGroup.O_NEG,
            'notes': 'Serology typing confirmed O Negative.'
        })
        self.assertRedirects(res, reverse('inventory:unit_detail', kwargs={'bag_id': self.unit.bag_id}))

        self.unit.refresh_from_db()
        self.assertEqual(self.unit.blood_group, BloodGroup.O_NEG)
        self.assertEqual(self.unit.lab_confirmed_by, self.staff)

        # Donor self-reported blood group is STILL A+
        self.donor.refresh_from_db()
        self.assertEqual(self.donor.blood_group, BloodGroup.A_POS)

    def test_update_unit_blood_group_form_post_rejects_invalid_values(self):
        """Staff POST with invalid blood group returns 400 with form error."""
        self.client.login(username=self.staff.username, password='password123')
        post_url = reverse('inventory:update_blood_group', kwargs={'bag_id': self.unit.bag_id})

        res = self.client.post(post_url, {
            'blood_group': 'INVALID_GROUP',
            'notes': 'Typo'
        })
        self.assertEqual(res.status_code, 400)
        self.unit.refresh_from_db()
        self.assertEqual(self.unit.blood_group, BloodGroup.A_POS)

    def test_update_unit_blood_group_rejects_unauthorized_roles(self):
        """Donor and hospital users are rejected with HTTP 403 Forbidden on update view."""
        post_url = reverse('inventory:update_blood_group', kwargs={'bag_id': self.unit.bag_id})

        # Donor attempt
        self.client.login(username=self.donor.username, password='password123')
        res = self.client.post(post_url, {'blood_group': BloodGroup.B_POS})
        self.assertEqual(res.status_code, 403)

        # Hospital attempt
        self.client.login(username=self.hospital.username, password='password123')
        res = self.client.post(post_url, {'blood_group': BloodGroup.B_POS})
        self.assertEqual(res.status_code, 403)

        # Unit unchanged
        self.unit.refresh_from_db()
        self.assertEqual(self.unit.blood_group, BloodGroup.A_POS)

    def test_api_update_blood_group_json_success(self):
        """Staff can update blood group via JSON API (SAD 4.3)."""
        self.client.login(username=self.staff.username, password='password123')
        api_url = reverse('api_blood_unit_blood_group', kwargs={'bag_id': self.unit.bag_id})

        payload = {
            'blood_group': BloodGroup.AB_NEG,
            'notes': 'API serology update'
        }
        res = self.client.post(
            api_url,
            data=json.dumps(payload),
            content_type='application/json'
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data['success'])
        self.assertEqual(data['blood_group'], BloodGroup.AB_NEG)
        self.assertEqual(data['bag_id'], self.unit.bag_id)
        self.assertEqual(data['donor_self_reported_group'], BloodGroup.A_POS)

        self.unit.refresh_from_db()
        self.assertEqual(self.unit.blood_group, BloodGroup.AB_NEG)
        self.assertEqual(self.unit.lab_confirmed_by, self.staff)

    def test_api_update_blood_group_rejects_invalid_value(self):
        """API rejects invalid blood group with 400 Bad Request."""
        self.client.login(username=self.staff.username, password='password123')
        api_url = reverse('api_blood_unit_blood_group', kwargs={'bag_id': self.unit.bag_id})

        payload = {'blood_group': 'C+'}
        res = self.client.post(
            api_url,
            data=json.dumps(payload),
            content_type='application/json'
        )
        self.assertEqual(res.status_code, 400)
        data = res.json()
        self.assertIn('Invalid blood group', data['error'])

    def test_api_update_blood_group_rejects_unauthenticated_and_unauthorized(self):
        """API denies unauthenticated (401) and non-staff (403)."""
        api_url = reverse('api_blood_unit_blood_group', kwargs={'bag_id': self.unit.bag_id})
        payload = json.dumps({'blood_group': BloodGroup.O_NEG})

        # Unauthenticated
        res = self.client.post(api_url, data=payload, content_type='application/json')
        self.assertEqual(res.status_code, 401)

        # Donor
        self.client.login(username=self.donor.username, password='password123')
        res = self.client.post(api_url, data=payload, content_type='application/json')
        self.assertEqual(res.status_code, 403)

        # Hospital
        self.client.login(username=self.hospital.username, password='password123')
        res = self.client.post(api_url, data=payload, content_type='application/json')
        self.assertEqual(res.status_code, 403)


class BloodGroupWorkflowIntegrationTests(TestCase):
    """
    Tests ensuring blood group data is integrated with inventory and quarantine workflows:
    - Inventory dashboard reflects units grouped by ABO/Rh blood groups (BBMS-F-033)
    - Quarantine list displays quarantined units with blood group and elapsed days (BBMS-F-030)
    - Public availability excludes quarantined/discarded units and donor PII (BBMS-F-028, F-067, F-068)
    """
    def setUp(self):
        self.client = Client()
        self.staff = User.objects.create_user(
            username='staff_flow',
            password='password123',
            role=User.Role.STAFF
        )

        # Create units in different states and blood groups
        self.u_avail_a = BloodUnit.objects.create(
            blood_group=BloodGroup.A_POS,
            status=BloodUnitStatus.AVAILABLE,
            component_type=ComponentType.WHOLE_BLOOD
        )
        self.u_avail_o = BloodUnit.objects.create(
            blood_group=BloodGroup.O_NEG,
            status=BloodUnitStatus.AVAILABLE,
            component_type=ComponentType.RBC
        )
        self.u_quarantined = BloodUnit.objects.create(
            blood_group=BloodGroup.B_POS,
            status=BloodUnitStatus.QUARANTINED,
            component_type=ComponentType.WHOLE_BLOOD
        )
        self.u_discarded = BloodUnit.objects.create(
            blood_group=BloodGroup.AB_POS,
            status=BloodUnitStatus.DISCARDED,
            component_type=ComponentType.WHOLE_BLOOD
        )

    def test_inventory_dashboard_aggregates_available_units(self):
        """Dashboard displays available unit counts grouped by blood group; excludes quarantined/discarded."""
        self.client.login(username=self.staff.username, password='password123')
        res = self.client.get(reverse('inventory:dashboard'))
        self.assertEqual(res.status_code, 200)

        # Total available is 2 (A+ and O-), quarantined is 1 (B+)
        self.assertEqual(res.context['total_units_available'], 2)
        self.assertEqual(res.context['quarantined_units'], 1)

        # Verify A+ row has 1 whole blood unit
        a_row = next(item for item in res.context['stock_matrix'] if item['blood_group'] == BloodGroup.A_POS)
        self.assertEqual(a_row['whole_blood'], 1)
        self.assertEqual(a_row['total'], 1)

        # Verify O- row has 1 RBC unit
        o_row = next(item for item in res.context['stock_matrix'] if item['blood_group'] == BloodGroup.O_NEG)
        self.assertEqual(o_row['rbc'], 1)
        self.assertEqual(o_row['total'], 1)

        # Verify AB+ (Discarded) has 0 available units
        ab_row = next(item for item in res.context['stock_matrix'] if item['blood_group'] == BloodGroup.AB_POS)
        self.assertEqual(ab_row['total'], 0)

    def test_quarantine_list_displays_quarantined_unit(self):
        """Quarantine list shows the quarantined B+ unit and excludes Available/Discarded units."""
        self.client.login(username=self.staff.username, password='password123')
        res = self.client.get(reverse('inventory:quarantine'))
        self.assertEqual(res.status_code, 200)

        quarantined_list = list(res.context['quarantined_units'])
        self.assertIn(self.u_quarantined, quarantined_list)
        self.assertNotIn(self.u_avail_a, quarantined_list)
        self.assertNotIn(self.u_discarded, quarantined_list)
        self.assertContains(res, self.u_quarantined.bag_id)
        self.assertContains(res, BloodGroup.B_POS)

    def test_public_availability_reflects_available_groups_without_pii(self):
        """Public availability endpoint counts only Available units and contains no PII."""
        res = self.client.get(reverse('core:public_availability'))
        self.assertEqual(res.status_code, 200)

        # Only Available A+ and O- have > 0 counts
        summary = res.context['inventory_summary']
        a_entry = next(e for e in summary if e['blood_group'] == BloodGroup.A_POS)
        self.assertEqual(a_entry['units'], 1)

        # Quarantined B+ unit must NOT be counted as available
        b_entry = next(e for e in summary if e['blood_group'] == BloodGroup.B_POS)
        self.assertEqual(b_entry['units'], 0)

        # No donor or bag ID PII in response
        self.assertNotContains(res, self.u_avail_a.bag_id)
        self.assertNotContains(res, 'staff_flow')
