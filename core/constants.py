"""
Shared constants, choices, and validation rules for Blood Bank Management System (BBMS).
SRS References:
- Section 4.7 (BBMS-F-022, BBMS-F-023): ABO/Rh Blood Group Management
- Section 4.16 (BBMS-F-049): Blood Compatibility and Cross-Matching
"""
from django.core.exceptions import ValidationError
from django.db import models


class BloodGroup(models.TextChoices):
    """
    Standard eight ABO/Rh blood groups supported throughout BBMS.
    SRS BBMS-F-022: 'The system shall support the eight standard ABO/Rh blood groups
    (A+, A-, B+, B-, AB+, AB-, O+, O-) for donor and blood-unit records.'
    """
    A_POS = 'A+', 'A+'
    A_NEG = 'A-', 'A-'
    B_POS = 'B+', 'B-'
    B_NEG = 'B-', 'B-'
    AB_POS = 'AB+', 'AB+'
    AB_NEG = 'AB-', 'AB-'
    O_POS = 'O+', 'O+'
    O_NEG = 'O-', 'O-'


# Tuple of all valid ABO/Rh blood group string representations
VALID_BLOOD_GROUPS = tuple(choice[0] for choice in BloodGroup.choices)


def is_valid_blood_group(value):
    """
    Check if a value is one of the eight valid ABO/Rh blood groups.
    Returns True if valid, False otherwise.
    """
    if not value or not isinstance(value, str):
        return False
    return value.strip().upper() in VALID_BLOOD_GROUPS


def validate_blood_group(value):
    """
    Model/form validator ensuring value is one of the eight standard ABO/Rh blood groups.
    Allows empty/None for optional fields; validates non-empty values.
    SRS BBMS-F-022.
    """
    if value in (None, ''):
        return
    normalized = str(value).strip().upper()
    if normalized not in VALID_BLOOD_GROUPS:
        raise ValidationError(
            f"'{value}' is not a valid ABO/Rh blood group. "
            f"Supported groups are: {', '.join(VALID_BLOOD_GROUPS)}."
        )


def validate_blood_group_required(value):
    """
    Strict validator requiring a non-empty, valid ABO/Rh blood group.
    """
    if not value:
        raise ValidationError("Blood group is required.")
    normalized = str(value).strip().upper()
    if normalized not in VALID_BLOOD_GROUPS:
        raise ValidationError(
            f"'{value}' is not a valid ABO/Rh blood group. "
            f"Supported groups are: {', '.join(VALID_BLOOD_GROUPS)}."
        )


# ==============================================================================
# Red Blood Cell (RBC) Transfusion Compatibility Matrix (SRS BBMS-F-049)
# Key: Recipient blood group
# Value: Tuple of compatible donor blood groups
# ==============================================================================
RBC_COMPATIBILITY_RULES = {
    BloodGroup.O_NEG: (BloodGroup.O_NEG,),
    BloodGroup.O_POS: (BloodGroup.O_NEG, BloodGroup.O_POS),
    BloodGroup.A_NEG: (BloodGroup.O_NEG, BloodGroup.A_NEG),
    BloodGroup.A_POS: (BloodGroup.O_NEG, BloodGroup.O_POS, BloodGroup.A_NEG, BloodGroup.A_POS),
    BloodGroup.B_NEG: (BloodGroup.O_NEG, BloodGroup.B_NEG),
    BloodGroup.B_POS: (BloodGroup.O_NEG, BloodGroup.O_POS, BloodGroup.B_NEG, BloodGroup.B_POS),
    BloodGroup.AB_NEG: (BloodGroup.O_NEG, BloodGroup.A_NEG, BloodGroup.B_NEG, BloodGroup.AB_NEG),
    BloodGroup.AB_POS: (
        BloodGroup.O_NEG, BloodGroup.O_POS,
        BloodGroup.A_NEG, BloodGroup.A_POS,
        BloodGroup.B_NEG, BloodGroup.B_POS,
        BloodGroup.AB_NEG, BloodGroup.AB_POS
    ),
}


def is_blood_compatible(donor_group, recipient_group):
    """
    Determine if a donor blood group is compatible for transfusion to a recipient.
    SRS BBMS-F-049.
    """
    if not donor_group or not recipient_group:
        return False
    compatible_donors = RBC_COMPATIBILITY_RULES.get(recipient_group, ())
    return donor_group in compatible_donors


def get_compatible_donor_groups(recipient_group):
    """
    Retrieve tuple of compatible donor blood groups for a given recipient group.
    SRS BBMS-F-049.
    """
    return RBC_COMPATIBILITY_RULES.get(recipient_group, ())
