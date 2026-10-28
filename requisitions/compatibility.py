"""
Transfusion Compatibility and Cross-Matching Policy Service.
SRS References:
- Section 4.16 (BBMS-F-049 to BBMS-F-051): Blood Compatibility and Cross-Matching
- Section 6.1 (BBMS-SR-004, BBMS-SR-008): Allocation Safety & Integrity
- SAD Section 3.4 / 4.3: POST /api/requests/{id}/cross-match

Academic Assumptions & Clinical Scope (Issue #36):
- Red Blood Cells (RBC) & Whole Blood: Evaluated against standard ABO/Rh erythrocyte
  antigen-antibody compatibility (SRS BBMS-F-049, core.constants.RBC_COMPATIBILITY_RULES).
  O-negative is universal RBC donor; AB-positive is universal RBC recipient.
- Fresh Frozen Plasma (FFP): Plasma contains anti-A and anti-B isohemagglutinins rather
  than cell-surface antigens. Consequently, plasma compatibility operates inversely to RBC:
  AB plasma lacks anti-A and anti-B antibodies and is the universal plasma donor, whereas
  Group O plasma contains both anti-A and anti-B antibodies and can only be safely transfused
  to Group O recipients. Rh factor in acellular plasma is non-immunogenic for routine transfusion,
  permitting Rh+ or Rh- plasma across Rh types when identical stock is depleted.
- Platelets: Transfusion of ABO-identical platelets is optimal to maximize post-transfusion
  increment. When identical stock is unavailable, ABO-compatible (RBC-compatible) units are
  permitted per standard hospital transfusion guidelines.
"""
from core.constants import BloodGroup, RBC_COMPATIBILITY_RULES
from inventory.models import ComponentType


# ==============================================================================
# Fresh Frozen Plasma (FFP) Transfusion Compatibility Matrix (BBMS-F-049)
# Key: Recipient ABO group (ignoring Rh for acellular plasma)
# Value: Tuple of compatible donor ABO blood groups
# ==============================================================================
PLASMA_ABO_COMPATIBILITY = {
    'O': ('O', 'A', 'B', 'AB'),
    'A': ('A', 'AB'),
    'B': ('B', 'AB'),
    'AB': ('AB',),
}


def _split_abo_rh(blood_group):
    """Splits an ABO/Rh string (e.g. 'AB+') into ('AB', '+')."""
    if not blood_group:
        return '', ''
    bg = blood_group.strip().upper()
    if bg.endswith('+') or bg.endswith('-'):
        return bg[:-1], bg[-1]
    return bg, ''


def get_compatible_donor_groups(recipient_group, component_type=ComponentType.RBC):
    """
    Retrieves the tuple of compatible donor blood groups for a given recipient
    group and component type (SRS BBMS-F-049).

    Parameters:
        recipient_group: String ABO/Rh group (e.g. 'A+', 'O-').
        component_type: ComponentType value (default RBC).

    Returns:
        tuple of compatible BloodGroup strings.
    """
    if not recipient_group:
        return ()

    recipient_group = recipient_group.strip().upper()

    # 1. Whole Blood & RBC: Standard erythrocyte antigen compatibility
    if component_type in (ComponentType.RBC, ComponentType.WHOLE_BLOOD):
        return RBC_COMPATIBILITY_RULES.get(recipient_group, ())

    # 2. Fresh Frozen Plasma (FFP): Inverse antibody compatibility
    if component_type == ComponentType.PLASMA:
        abo_rec, _ = _split_abo_rh(recipient_group)
        compatible_abo = PLASMA_ABO_COMPATIBILITY.get(abo_rec, ())

        compatible_donors = []
        # Return all ABO/Rh donor combinations whose ABO part is compatible
        for donor_bg in BloodGroup.values:
            donor_abo, _ = _split_abo_rh(donor_bg)
            if donor_abo in compatible_abo:
                compatible_donors.append(donor_bg)
        return tuple(compatible_donors)

    # 3. Platelets: Identical group preferred, RBC-compatible acceptable
    if component_type == ComponentType.PLATELETS:
        return RBC_COMPATIBILITY_RULES.get(recipient_group, ())

    return RBC_COMPATIBILITY_RULES.get(recipient_group, ())


def is_transfusion_compatible(donor_group, recipient_group, component_type=ComponentType.RBC):
    """
    Determines if donor blood is biologically compatible for transfusion to recipient
    given the specific blood component type (SRS BBMS-F-049).
    """
    if not donor_group or not recipient_group:
        return False
    d_clean = donor_group.strip().upper()
    r_clean = recipient_group.strip().upper()
    compatible_groups = get_compatible_donor_groups(r_clean, component_type)
    return d_clean in compatible_groups


def explain_compatibility(donor_group, recipient_group, component_type=ComponentType.RBC):
    """
    Provides a clinical explanation of the compatibility determination for auditing and UI.
    """
    if not donor_group or not recipient_group:
        return "Incomplete blood group information."

    d_clean = donor_group.strip().upper()
    r_clean = recipient_group.strip().upper()
    is_compat = is_transfusion_compatible(d_clean, r_clean, component_type)

    if component_type in (ComponentType.RBC, ComponentType.WHOLE_BLOOD):
        if is_compat:
            if d_clean == r_clean:
                return f"ABO/Rh identical match ({d_clean} to {r_clean})."
            if d_clean == BloodGroup.O_NEG:
                return f"Universal donor RBC match (O- to {r_clean})."
            return f"Compatible RBC match ({d_clean} to {r_clean})."
        return (
            f"ABO/Rh incompatible RBC match ({d_clean} to {r_clean}). "
            f"Recipient antibodies will hemolyze donor red cells."
        )

    if component_type == ComponentType.PLASMA:
        if is_compat:
            d_abo, _ = _split_abo_rh(d_clean)
            if d_abo == 'AB':
                return f"Universal plasma donor match ({d_clean} to {r_clean}, lacks anti-A/B)."
            return f"Compatible plasma match ({d_clean} to {r_clean})."
        return (
            f"Incompatible plasma match ({d_clean} to {r_clean}). "
            f"Donor plasma contains isohemagglutinins against recipient red cells."
        )

    if component_type == ComponentType.PLATELETS:
        if is_compat:
            if d_clean == r_clean:
                return f"Identical platelet match ({d_clean} to {r_clean})."
            return f"Compatible platelet match ({d_clean} to {r_clean})."
        return f"Incompatible platelet match ({d_clean} to {r_clean})."

    return f"Match result: {'Compatible' if is_compat else 'Incompatible'}."
