"""
Inventory models for Blood Bank Management System (BBMS).
SRS References:
- Section 4.6 (BBMS-F-020, BBMS-F-021): Unique Blood Unit / Bag ID
- Section 4.7 (BBMS-F-022, BBMS-F-023): Blood Group Management
- Section 4.8 (BBMS-F-024 to BBMS-F-027): Serology Testing & Quarantine
- Section 4.9 (BBMS-F-028 to BBMS-F-030): Quarantine of Unsafe Blood
- Section 4.10 (BBMS-F-031, BBMS-F-032): Component Separation Traceability
- Section 4.11 (BBMS-F-033 to BBMS-F-036): Blood Inventory Management
- Section 4.12 (BBMS-F-037 to BBMS-F-039): Expiry Handling & FEFO
"""
import uuid
from datetime import timedelta
from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import models
from django.utils import timezone

from core.constants import BloodGroup, VALID_BLOOD_GROUPS, validate_blood_group


class BloodUnitStatus(models.TextChoices):
    """
    Lifecycle status values for a blood unit.
    SRS BBMS-F-026, BBMS-F-027, BBMS-F-039, BBMS-F-054, BBMS-F-057.
    """
    QUARANTINED = 'Quarantined', 'Quarantined'
    AVAILABLE = 'Available', 'Available'
    ALLOCATED = 'Allocated', 'Allocated'
    DISPATCHED = 'Dispatched', 'Dispatched'
    DELIVERED = 'Delivered', 'Delivered'
    DISCARDED = 'Discarded', 'Discarded'
    EXPIRED = 'Expired', 'Expired'


class ComponentType(models.TextChoices):
    """
    Standard blood component types.
    SRS BBMS-F-031, BBMS-F-037.
    """
    WHOLE_BLOOD = 'Whole Blood', 'Whole Blood'
    RBC = 'Red Blood Cells', 'Red Blood Cells'
    PLATELETS = 'Platelets', 'Platelets'
    PLASMA = 'Fresh Frozen Plasma', 'Fresh Frozen Plasma'


# Standard shelf lives per component type (SRS BBMS-F-037)
COMPONENT_SHELF_LIFE_DAYS = {
    ComponentType.WHOLE_BLOOD: 42,
    ComponentType.RBC: 42,
    ComponentType.PLATELETS: 5,
    ComponentType.PLASMA: 365,
}


class SerologyTestType(models.TextChoices):
    """
    Standard mandatory serology infection test types per SRS BBMS-F-024.
    Every unit must be tested for HIV, Hepatitis B, Hepatitis C, and Syphilis.
    """
    HIV = 'HIV', 'HIV'
    HEPATITIS_B = 'Hepatitis B', 'Hepatitis B'
    HEPATITIS_C = 'Hepatitis C', 'Hepatitis C'
    SYPHILIS = 'Syphilis', 'Syphilis'


REQUIRED_SEROLOGY_TESTS = [
    SerologyTestType.HIV,
    SerologyTestType.HEPATITIS_B,
    SerologyTestType.HEPATITIS_C,
    SerologyTestType.SYPHILIS,
]


class SerologyResult(models.TextChoices):
    """
    Serology test outcomes per SRS BBMS-F-025.
    """
    PASS = 'Pass', 'Pass'
    FAIL = 'Fail', 'Fail'


class BloodUnitQuerySet(models.QuerySet):
    """
    Custom QuerySet for BloodUnit model.
    SRS References:
    - BBMS-F-028: Exclude Quarantined and Discarded units from availability counts and search results.
    - BBMS-F-033: Real-time available blood unit counts.
    - BBMS-F-039: Exclude expired units from availability counts.
    """
    def available(self):
        """
        Returns only blood units that are marked 'Available' and have not expired (BBMS-F-028, BBMS-F-039).
        Guarantees Quarantined and Discarded units are excluded from inventory availability and hospital searches.
        """
        return self.filter(
            status=BloodUnitStatus.AVAILABLE,
            expiry_date__gt=timezone.now()
        )

    def quarantined(self):
        """Returns units currently in Quarantined status (BBMS-F-030)."""
        return self.filter(status=BloodUnitStatus.QUARANTINED)

    def discarded(self):
        """Returns units that have been marked Discarded (BBMS-F-027)."""
        return self.filter(status=BloodUnitStatus.DISCARDED)


class BloodUnit(models.Model):
    """
    Represents a collected blood bag / unit.
    Stores laboratory-confirmed blood group separately from donor self-reported blood group.
    SRS BBMS-F-020 to BBMS-F-023.
    """
    bag_id = models.CharField(
        max_length=32,
        unique=True,
        db_index=True,
        help_text='Unique identifier assigned to a collected blood unit (SRS BBMS-F-020, BBMS-F-021)'
    )
    donor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='donations',
        help_text='Associated donor account (SRS BBMS-F-019)'
    )
    blood_group = models.CharField(
        max_length=5,
        choices=BloodGroup.choices,
        validators=[validate_blood_group],
        help_text='Laboratory-confirmed ABO/Rh blood group, distinct from donor self-report (SRS BBMS-F-022, BBMS-F-023)'
    )
    status = models.CharField(
        max_length=20,
        choices=BloodUnitStatus.choices,
        default=BloodUnitStatus.QUARANTINED,
        db_index=True,
        help_text='Current unit status. Defaults to Quarantined upon collection (SRS BBMS-F-026)'
    )
    component_type = models.CharField(
        max_length=30,
        choices=ComponentType.choices,
        default=ComponentType.WHOLE_BLOOD,
        help_text='Component type (SRS BBMS-F-031, BBMS-F-037)'
    )
    volume_ml = models.PositiveIntegerField(
        default=450,
        help_text='Collected volume in millilitres (SRS BBMS-F-018)'
    )
    collection_date = models.DateTimeField(
        default=timezone.now,
        help_text='Collection timestamp (SRS BBMS-F-018)'
    )
    expiry_date = models.DateTimeField(
        null=True,
        blank=True,
        help_text='Calculated expiry date based on component type and availability (SRS BBMS-F-037)'
    )
    location = models.CharField(
        max_length=100,
        default='Central Blood Bank',
        help_text='Blood bank storage facility location (SRS BBMS-F-033)'
    )
    parent_unit = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='child_components',
        help_text='Traceability reference to originating whole-blood unit Bag ID (SRS BBMS-F-032)'
    )

    # Blood Collection Staff & Audit Details (SRS BBMS-F-017, BBMS-F-018)
    collected_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='collected_blood_units',
        help_text='Authorized staff member who recorded this blood collection (SRS BBMS-F-017)'
    )
    collection_notes = models.TextField(
        blank=True,
        help_text='Staff notes or clinical observations made during donation (SRS BBMS-F-018)'
    )

    # Laboratory Confirmation & Correction Audit Trail (SRS BBMS-F-023, BBMS-F-058)
    lab_confirmed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='confirmed_blood_units',
        help_text='Authorized staff member who confirmed or corrected this blood group (SRS BBMS-F-023)'
    )
    lab_confirmed_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text='Timestamp of laboratory blood group recording/correction (SRS BBMS-F-023)'
    )
    blood_group_notes = models.TextField(
        blank=True,
        help_text='Staff rationale or notes on blood group determination/correction (SRS BBMS-F-023)'
    )
    status_audit_log = models.TextField(
        blank=True,
        help_text='Audit log of status transitions and serology outcomes (SRS BBMS-F-029)'
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-collection_date']
        verbose_name = 'Blood Unit'
        verbose_name_plural = 'Blood Units'

    objects = BloodUnitQuerySet.as_manager()

    @classmethod
    def generate_unique_bag_id(cls, prefix='BAG'):
        """
        Generate a globally unique Bag ID per SRS BBMS-F-020.
        Format: BAG-<YYYYMMDD>-<HEX6> (e.g. BAG-20261020-A1B2C3)
        """
        date_str = timezone.now().strftime('%Y%m%d')
        while True:
            candidate = f"{prefix}-{date_str}-{uuid.uuid4().hex[:6].upper()}"
            if not cls.objects.filter(bag_id=candidate).exists():
                return candidate

    @classmethod
    def calculate_default_expiry(cls, component_type, from_date=None):
        """
        Calculate expiry date based on component type per SRS BBMS-F-037.
        - Whole Blood / RBC: 42 days
        - Platelets: 5 days
        - Fresh Frozen Plasma: 365 days
        """
        base_date = from_date or timezone.now()
        shelf_days = COMPONENT_SHELF_LIFE_DAYS.get(component_type, 42)
        return base_date + timedelta(days=shelf_days)

    @classmethod
    def record_collection(
        cls,
        staff_user,
        donor,
        blood_group,
        volume_ml=450,
        component_type=ComponentType.WHOLE_BLOOD,
        collection_date=None,
        location='Central Blood Bank',
        notes=''
    ):
        """
        Record a completed blood collection with automatic unique Bag ID generation.
        SRS References:
        - BBMS-F-017: Staff authorization check
        - BBMS-F-018: Volume and collection timestamp recording
        - BBMS-F-019: Association with donor and history tracking
        - BBMS-F-020: Automatic unique Bag ID generation
        - BBMS-F-021: Unique Bag ID enforcement
        - BBMS-F-026: Default Quarantined status
        """
        if staff_user is not None:
            user_role = getattr(staff_user, 'role', None)
            is_authorized = (
                user_role in ('STAFF', 'ADMIN') or
                getattr(staff_user, 'is_staff', False) or
                getattr(staff_user, 'is_superuser', False)
            )
            if not is_authorized:
                raise PermissionDenied(
                    "Only authorized blood bank staff or administrators can record blood collections "
                    "(SRS BBMS-F-017, BBMS-SR-003)."
                )

        if not donor:
            raise ValidationError("A donor must be specified for blood collection (SRS BBMS-F-017).")

        donor_role = getattr(donor, 'role', None)
        if donor_role and donor_role != 'DONOR':
            raise ValidationError("Blood collection must be associated with a valid registered donor (SRS BBMS-F-019).")

        if volume_ml is None or volume_ml <= 0:
            raise ValidationError("Collected volume must be greater than 0 mL.")
        if volume_ml < 200 or volume_ml > 600:
            raise ValidationError(
                f"Collected volume {volume_ml} mL is outside the standard acceptable donation range (200-600 mL)."
            )

        if not blood_group:
            raise ValidationError("Blood group is required.")
        normalized_bg = str(blood_group).strip().upper()
        validate_blood_group(normalized_bg)

        c_date = collection_date or timezone.now()
        bag_id = cls.generate_unique_bag_id()

        unit = cls(
            bag_id=bag_id,
            donor=donor,
            collected_by=staff_user,
            blood_group=normalized_bg,
            component_type=component_type,
            volume_ml=volume_ml,
            collection_date=c_date,
            status=BloodUnitStatus.QUARANTINED,
            location=location,
            collection_notes=notes,
        )
        unit.save()
        return unit

    @property
    def is_available(self):
        """Returns True if the blood unit is cleared and available for allocation."""
        return self.status == BloodUnitStatus.AVAILABLE

    @property
    def is_quarantined(self):
        """Returns True if the blood unit is quarantined pending testing or inspection."""
        return self.status == BloodUnitStatus.QUARANTINED

    @property
    def is_discarded(self):
        """Returns True if the blood unit has been discarded (BBMS-F-027)."""
        return self.status == BloodUnitStatus.DISCARDED

    @property
    def is_expired(self):
        """Checks if current time has passed the unit's expiry date (SRS BBMS-F-039)."""
        if not self.expiry_date:
            return False
        return timezone.now() > self.expiry_date

    @property
    def has_passed_serology(self):
        """
        Returns True if all 4 mandatory serology tests (HIV, Hepatitis B, Hepatitis C, Syphilis)
        have been recorded as Pass (SRS BBMS-F-024, BBMS-F-026).
        """
        if not self.pk:
            return False
        tests = {t.test_type: t.result for t in self.serology_tests.all()}
        return (
            all(req in tests for req in REQUIRED_SEROLOGY_TESTS) and
            all(tests[req] == SerologyResult.PASS for req in REQUIRED_SEROLOGY_TESTS)
        )

    @property
    def serology_summary(self):
        """Returns structured dictionary of serology test statuses for templates/APIs."""
        existing = {t.test_type: t for t in self.serology_tests.all()} if self.pk else {}
        summary = {}
        for req in REQUIRED_SEROLOGY_TESTS:
            if req in existing:
                test = existing[req]
                summary[req] = {
                    'recorded': True,
                    'result': test.result,
                    'tested_by': test.tested_by.username if test.tested_by else None,
                    'tested_at': test.tested_at,
                    'notes': test.notes,
                }
            else:
                summary[req] = {
                    'recorded': False,
                    'result': None,
                    'tested_by': None,
                    'tested_at': None,
                    'notes': '',
                }
        return summary

    @property
    def donor_self_reported_group(self):
        """
        Returns the donor's self-reported blood group for comparison.
        Demonstrates independent storage per SRS BBMS-F-023.
        """
        if self.donor:
            return getattr(self.donor, 'blood_group', None)
        return None

    @property
    def quarantine_duration_days(self):
        """
        Calculates elapsed time in quarantine (SRS BBMS-F-030).
        """
        if not self.is_quarantined:
            return None
        elapsed = timezone.now() - self.collection_date
        return round(elapsed.total_seconds() / 86400, 1)

    def clean(self):
        super().clean()
        if self.blood_group:
            validate_blood_group(self.blood_group)

        if self.pk:
            has_failed_tests = self.serology_tests.filter(result=SerologyResult.FAIL).exists()
            if has_failed_tests and self.status != BloodUnitStatus.DISCARDED:
                raise ValidationError(
                    "A blood unit with any failed serology test must be marked Discarded and cannot be "
                    "made Available or Quarantined (SRS BBMS-F-027)."
                )

            if self.status == BloodUnitStatus.AVAILABLE and not self.has_passed_serology:
                orig = BloodUnit.objects.filter(pk=self.pk).values('status').first()
                if orig and orig['status'] != BloodUnitStatus.AVAILABLE:
                    raise ValidationError(
                        "A blood unit cannot be marked Available until all four required serology tests "
                        "(HIV, Hepatitis B, Hepatitis C, Syphilis) have been recorded as Pass "
                        "(SRS BBMS-F-024, BBMS-F-026)."
                    )

    def save(self, *args, **kwargs):
        if not self.bag_id:
            self.bag_id = self.generate_unique_bag_id()
        if not self.expiry_date and self.component_type:
            self.expiry_date = self.calculate_default_expiry(self.component_type, self.collection_date)
        self.clean()
        super().save(*args, **kwargs)

    def log_status_change(self, old_status, new_status, actor=None, reason=''):
        """
        Logs status transition audit trail per SRS BBMS-F-029.
        Logs identity of the staff member and timestamp whenever unit status changes to or from Quarantined.
        """
        if old_status == new_status:
            return
        timestamp_str = timezone.now().strftime('%Y-%m-%d %H:%M:%S')
        actor_display = getattr(actor, 'username', 'Staff') if actor else 'System'
        entry = (
            f"[{timestamp_str}] Status transitioned from '{old_status}' to '{new_status}' "
            f"by {actor_display}."
        )
        if reason:
            entry += f" Reason: {reason}"
        if self.status_audit_log:
            self.status_audit_log += f"\n{entry}"
        else:
            self.status_audit_log = entry

    def evaluate_serology_status(self, actor=None, save=True):
        """
        Evaluates the serology panel results and executes automated quarantine transition rules.
        SRS References:
        - BBMS-F-024: All 4 tests (HIV, Hepatitis B, Hepatitis C, Syphilis) required before Available.
        - BBMS-F-026: Defaults to Quarantined; only transitions to Available if all 4 tests pass.
        - BBMS-F-027: Transitions to Discarded if any serology test fails; blocks allocation.
        - BBMS-F-029: Logs status changes to/from Quarantined with staff ID and timestamp.
        - BBMS-F-037: Calculates and stores expiry date (e.g. 42 days for Whole Blood/RBC) when marked Available.
        """
        if not self.pk:
            return self.status, "Unit must be saved before evaluating serology status."

        tests = {t.test_type: t.result for t in self.serology_tests.all()}
        old_status = self.status

        # 1. Any Fail -> Discarded (BBMS-F-027)
        if any(r == SerologyResult.FAIL for r in tests.values()):
            failed_tests = [k for k, v in tests.items() if v == SerologyResult.FAIL]
            self.status = BloodUnitStatus.DISCARDED
            self.log_status_change(
                old_status=old_status,
                new_status=BloodUnitStatus.DISCARDED,
                actor=actor,
                reason=f"Failed serology test(s): {', '.join(failed_tests)}"
            )
            if save:
                self.save()
            return self.status, f"Unit discarded due to failed test(s): {', '.join(failed_tests)}."

        # 2. All 4 tests recorded and all are Pass -> Available (BBMS-F-026, BBMS-F-037)
        has_all_required = all(t in tests for t in REQUIRED_SEROLOGY_TESTS)
        all_passed = has_all_required and all(tests[t] == SerologyResult.PASS for t in REQUIRED_SEROLOGY_TESTS)

        if all_passed:
            self.status = BloodUnitStatus.AVAILABLE
            self.expiry_date = self.calculate_default_expiry(self.component_type, self.collection_date)
            self.log_status_change(
                old_status=old_status,
                new_status=BloodUnitStatus.AVAILABLE,
                actor=actor,
                reason="All required serology tests (HIV, Hep B, Hep C, Syphilis) passed."
            )
            if save:
                self.save()
            return self.status, "All required serology tests passed. Unit marked Available."

        # 3. Missing tests or incomplete panel -> remains Quarantined (BBMS-F-026)
        missing_tests = [t for t in REQUIRED_SEROLOGY_TESTS if t not in tests]
        self.status = BloodUnitStatus.QUARANTINED
        if old_status != BloodUnitStatus.QUARANTINED:
            self.log_status_change(
                old_status=old_status,
                new_status=BloodUnitStatus.QUARANTINED,
                actor=actor,
                reason=f"Incomplete serology panel. Pending: {', '.join(missing_tests)}"
            )
        if save:
            self.save()
        return self.status, f"Unit remains Quarantined pending tests: {', '.join(missing_tests)}."

    def record_serology_test(self, test_type, result, staff_user=None, notes=''):
        """
        Records a single serology test result with staff authorization verification (BBMS-F-025, BBMS-SR-003).
        Automatically triggers evaluate_serology_status().
        """
        if staff_user is not None:
            user_role = getattr(staff_user, 'role', None)
            is_authorized = (
                user_role in ('STAFF', 'ADMIN') or
                getattr(staff_user, 'is_staff', False) or
                getattr(staff_user, 'is_superuser', False)
            )
            if not is_authorized:
                raise PermissionDenied(
                    "Only authorized blood bank staff or administrators can record serology test results "
                    "(SRS BBMS-F-025, BBMS-SR-003)."
                )

        if not test_type or test_type not in SerologyTestType.values:
            raise ValidationError(
                f"Invalid serology test type '{test_type}'. Must be one of: {', '.join(SerologyTestType.values)}."
            )

        normalized_res = str(result).strip().title()
        if normalized_res not in SerologyResult.values:
            raise ValidationError(
                f"Invalid serology result '{result}'. Must be 'Pass' or 'Fail' (SRS BBMS-F-025)."
            )

        test_obj, _ = SerologyTest.objects.update_or_create(
            blood_unit=self,
            test_type=test_type,
            defaults={
                'result': normalized_res,
                'tested_by': staff_user,
                'tested_at': timezone.now(),
                'notes': notes,
            }
        )
        self.evaluate_serology_status(actor=staff_user, save=True)
        return test_obj

    def record_serology_panel(self, results_dict, staff_user=None, notes=''):
        """
        Records results for multiple or all required serology tests at once (BBMS-F-024, BBMS-F-025).
        results_dict: dict of {test_type: 'Pass'/'Fail'}
        """
        if staff_user is not None:
            user_role = getattr(staff_user, 'role', None)
            is_authorized = (
                user_role in ('STAFF', 'ADMIN') or
                getattr(staff_user, 'is_staff', False) or
                getattr(staff_user, 'is_superuser', False)
            )
            if not is_authorized:
                raise PermissionDenied(
                    "Only authorized blood bank staff or administrators can record serology test results "
                    "(SRS BBMS-F-025, BBMS-SR-003)."
                )

        recorded = {}
        for t_type, res in results_dict.items():
            if not res:
                continue
            if t_type not in SerologyTestType.values:
                raise ValidationError(f"Invalid test type '{t_type}'.")
            norm_res = str(res).strip().title()
            if norm_res not in SerologyResult.values:
                raise ValidationError(f"Invalid result '{res}' for {t_type}. Must be 'Pass' or 'Fail'.")

            test_obj, _ = SerologyTest.objects.update_or_create(
                blood_unit=self,
                test_type=t_type,
                defaults={
                    'result': norm_res,
                    'tested_by': staff_user,
                    'tested_at': timezone.now(),
                    'notes': notes,
                }
            )
            recorded[t_type] = test_obj

        self.evaluate_serology_status(actor=staff_user, save=True)
        return recorded

    def update_blood_group(self, new_blood_group, staff_user=None, notes=''):
        """
        Allows authorized blood bank staff to record or correct the laboratory-confirmed
        blood group of a blood unit (SRS BBMS-F-023).

        - Validates that new_blood_group is one of the 8 ABO/Rh valid groups.
        - Verifies that staff_user has STAFF or ADMIN role.
        - Stores the confirmed blood group independently; does NOT alter donor self-reported blood group.
        - Records responsible staff member and timestamp for auditing (SRS BBMS-F-058).
        """
        # 1. Authorization check
        if staff_user is not None:
            user_role = getattr(staff_user, 'role', None)
            is_authorized = (
                user_role in ('STAFF', 'ADMIN') or
                getattr(staff_user, 'is_staff', False) or
                getattr(staff_user, 'is_superuser', False)
            )
            if not is_authorized:
                raise PermissionDenied(
                    "Only authorized blood bank staff or administrators can record or correct blood groups "
                    "(SRS BBMS-F-023, BBMS-SR-003)."
                )

        # 2. Validation check
        if not new_blood_group:
            raise ValidationError("Blood group value cannot be empty.")

        normalized_group = str(new_blood_group).strip().upper()
        if normalized_group not in VALID_BLOOD_GROUPS:
            raise ValidationError(
                f"Invalid blood group '{new_blood_group}'. Supported values are: {', '.join(VALID_BLOOD_GROUPS)}."
            )

        # 3. Update lab-confirmed blood group and audit trail
        self.blood_group = normalized_group
        self.lab_confirmed_by = staff_user
        self.lab_confirmed_at = timezone.now()

        timestamp_str = timezone.now().strftime('%Y-%m-%d %H:%M')
        user_display = getattr(staff_user, 'username', 'Staff') if staff_user else 'Staff'
        log_entry = f"[{timestamp_str}] Blood group set to {normalized_group} by {user_display}."
        if notes:
            log_entry += f" Rationale: {notes}"

        if self.blood_group_notes:
            self.blood_group_notes += f"\n{log_entry}"
        else:
            self.blood_group_notes = log_entry

        # Save unit without modifying donor's self-reported blood group
        self.save()

    def __str__(self):
        bg = self.blood_group or "Pending"
        return f"{self.bag_id} ({bg}) - {self.component_type} [{self.status}]"


class SerologyTest(models.Model):
    """
    Stores individual serology / infection test result for a blood unit.
    SRS References:
    - BBMS-F-024: Mandatory serology testing for HIV, Hepatitis B, Hepatitis C, Syphilis.
    - BBMS-F-025: Pass/Fail recording per test.
    - BBMS-F-029: Staff audit identity and timestamp.
    """
    blood_unit = models.ForeignKey(
        BloodUnit,
        on_delete=models.CASCADE,
        related_name='serology_tests',
        help_text='Blood unit tested (SRS BBMS-F-024)'
    )
    test_type = models.CharField(
        max_length=20,
        choices=SerologyTestType.choices,
        help_text='Specific serological screening assay (SRS BBMS-F-024)'
    )
    result = models.CharField(
        max_length=10,
        choices=SerologyResult.choices,
        help_text='Test outcome: Pass or Fail (SRS BBMS-F-025)'
    )
    tested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='conducted_serology_tests',
        help_text='Authorized staff member who conducted or recorded the test (SRS BBMS-F-029)'
    )
    tested_at = models.DateTimeField(
        default=timezone.now,
        help_text='Timestamp when test result was recorded (SRS BBMS-F-029)'
    )
    notes = models.TextField(
        blank=True,
        help_text='Laboratory notes or assay optical density / reagent kit details'
    )

    class Meta:
        ordering = ['blood_unit', 'test_type']
        unique_together = [('blood_unit', 'test_type')]
        verbose_name = 'Serology Test'
        verbose_name_plural = 'Serology Tests'

    def __str__(self):
        return f"{self.blood_unit.bag_id} - {self.test_type}: {self.result}"

