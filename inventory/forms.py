"""
Forms for Blood Bank Inventory management.
SRS BBMS-F-022, BBMS-F-023.
"""
from django import forms
from core.constants import BloodGroup, VALID_BLOOD_GROUPS


class BloodGroupCorrectionForm(forms.Form):
    """
    Form enabling authorized blood bank staff to record or correct the
    laboratory-confirmed blood group of a blood unit (SRS BBMS-F-023).
    """
    blood_group = forms.ChoiceField(
        choices=BloodGroup.choices,
        label="Laboratory-Confirmed ABO/Rh Blood Group",
        widget=forms.Select(attrs={
            'class': 'form-select form-select-lg',
            'id': 'id_blood_group',
        }),
        help_text="Select verified ABO/Rh blood group following serological laboratory confirmation."
    )
    notes = forms.CharField(
        required=False,
        label="Confirmation / Correction Rationale",
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 3,
            'placeholder': (
                'Optional explanation (e.g. Initial lab serology typing, '
                'correction of prior typo, confirmation test).'
            ),
            'id': 'id_notes',
        }),
        help_text="Reason recorded in audit history for tracking this blood group assignment (SRS BBMS-F-058)."
    )

    def clean_blood_group(self):
        bg = self.cleaned_data.get('blood_group')
        if not bg or str(bg).strip().upper() not in VALID_BLOOD_GROUPS:
            raise forms.ValidationError(
                f"Invalid blood group '{bg}'. Valid blood groups: {', '.join(VALID_BLOOD_GROUPS)}."
            )
        return str(bg).strip().upper()
