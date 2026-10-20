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

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-collection_date']
        verbose_name = 'Blood Unit'
        verbose_name_plural = 'Blood Units'

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

    @property
    def is_available(self):
        """Returns True if the blood unit is cleared and available for allocation."""
        return self.status == BloodUnitStatus.AVAILABLE

    @property
    def is_quarantined(self):
        """Returns True if the blood unit is quarantined pending testing or inspection."""
        return self.status == BloodUnitStatus.QUARANTINED

    @property
    def is_expired(self):
        """Checks if current time has passed the unit's expiry date (SRS BBMS-F-039)."""
        if not self.expiry_date:
            return False
        return timezone.now() > self.expiry_date

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

    def save(self, *args, **kwargs):
        if not self.bag_id:
            self.bag_id = self.generate_unique_bag_id()
        if not self.expiry_date and self.component_type:
            self.expiry_date = self.calculate_default_expiry(self.component_type, self.collection_date)
        self.clean()
        super().save(*args, **kwargs)

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
