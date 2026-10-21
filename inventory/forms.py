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


class BloodCollectionForm(forms.ModelForm):
    """
    Form enabling authorized blood bank staff to record blood collections
    and automatically generate a unique Bag ID.
    SRS BBMS-F-017, BBMS-F-018, BBMS-F-019, BBMS-F-020, BBMS-F-021.
    """
    donor = forms.ModelChoiceField(
        queryset=None,
        label="Donor",
        widget=forms.Select(attrs={
            'class': 'form-select',
            'id': 'id_donor',
        }),
        help_text="Select registered donor donating blood (SRS BBMS-F-019)."
    )
    blood_group = forms.ChoiceField(
        choices=BloodGroup.choices,
        label="Laboratory-Confirmed ABO/Rh Blood Group",
        widget=forms.Select(attrs={
            'class': 'form-select',
            'id': 'id_blood_group',
        }),
        help_text="Confirmed blood group for collected unit (SRS BBMS-F-022)."
    )
    component_type = forms.ChoiceField(
        choices=(),
        label="Component Type",
        widget=forms.Select(attrs={
            'class': 'form-select',
            'id': 'id_component_type',
        }),
        help_text="Component type collected (SRS BBMS-F-031)."
    )
    volume_ml = forms.IntegerField(
        initial=450,
        min_value=200,
        max_value=600,
        label="Volume Collected (mL)",
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'id': 'id_volume_ml',
            'step': '10',
        }),
        help_text="Collected blood volume in millilitres. Standard adult donation is 450 mL (SRS BBMS-F-018)."
    )
    location = forms.CharField(
        initial="Central Blood Bank",
        max_length=100,
        label="Storage / Collection Facility",
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'id': 'id_location',
        }),
        help_text="Facility location where donation occurred (SRS BBMS-F-033)."
    )
    collection_notes = forms.CharField(
        required=False,
        label="Collection Notes",
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 2,
            'placeholder': 'Optional staff observations, donor vitals, or donation remarks...',
            'id': 'id_collection_notes',
        }),
        help_text="Clinical observations or remarks recorded by staff (SRS BBMS-F-018)."
    )

    class Meta:
        from .models import BloodUnit
        model = BloodUnit
        fields = ['donor', 'blood_group', 'component_type', 'volume_ml', 'location', 'collection_notes']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from accounts.models import User
        from .models import ComponentType
        self.fields['donor'].queryset = User.objects.filter(role=User.Role.DONOR).order_by(
            'first_name', 'last_name', 'username'
        )
        self.fields['component_type'].choices = ComponentType.choices
        self.fields['component_type'].initial = ComponentType.WHOLE_BLOOD

    def clean_donor(self):
        donor = self.cleaned_data.get('donor')
        if not donor:
            raise forms.ValidationError("Please select a registered donor.")
        if getattr(donor, 'role', None) != 'DONOR':
            raise forms.ValidationError("Selected user is not registered as a Donor.")
        return donor

    def clean_blood_group(self):
        bg = self.cleaned_data.get('blood_group')
        if not bg or str(bg).strip().upper() not in VALID_BLOOD_GROUPS:
            raise forms.ValidationError(f"Invalid blood group. Valid choices: {', '.join(VALID_BLOOD_GROUPS)}")
        return str(bg).strip().upper()

    def clean_volume_ml(self):
        vol = self.cleaned_data.get('volume_ml')
        if vol is None or vol <= 0:
            raise forms.ValidationError("Volume collected must be greater than 0 mL.")
        if vol < 200 or vol > 600:
            raise forms.ValidationError("Collected volume must be between 200 mL and 600 mL.")
        return vol

    def save(self, commit=True, staff_user=None):
        from .models import BloodUnit, BloodUnitStatus
        instance = super().save(commit=False)
        if not instance.bag_id:
            instance.bag_id = BloodUnit.generate_unique_bag_id()
        if staff_user is not None:
            instance.collected_by = staff_user
        instance.status = BloodUnitStatus.QUARANTINED
        if commit:
            instance.save()
        return instance


class SerologyPanelForm(forms.Form):
    """
    Form allowing authorized blood bank staff to record serology test outcomes
    for the mandatory infection markers (HIV, Hepatitis B, Hepatitis C, Syphilis).
    SRS References:
    - BBMS-F-024: Mandatory serology testing before Available.
    - BBMS-F-025: Pass/Fail recording for each test.
    - BBMS-F-026: Defaults to Quarantined; Available on all Pass.
    - BBMS-F-027: Discarded on any Fail.
    """
    CHOICES = [
        ('', '-- Select Outcome --'),
        ('Pass', 'Pass (Non-reactive / Negative)'),
        ('Fail', 'Fail (Reactive / Positive)'),
    ]

    hiv = forms.ChoiceField(
        choices=CHOICES,
        required=False,
        label="HIV 1/2 Screening",
        widget=forms.Select(attrs={
            'class': 'form-select',
            'id': 'id_serology_hiv',
        }),
        help_text="Human Immunodeficiency Virus antibodies / p24 antigen assay (SRS BBMS-F-024)."
    )
    hepatitis_b = forms.ChoiceField(
        choices=CHOICES,
        required=False,
        label="Hepatitis B (HBsAg)",
        widget=forms.Select(attrs={
            'class': 'form-select',
            'id': 'id_serology_hep_b',
        }),
        help_text="Hepatitis B surface antigen serological screening (SRS BBMS-F-024)."
    )
    hepatitis_c = forms.ChoiceField(
        choices=CHOICES,
        required=False,
        label="Hepatitis C (Anti-HCV)",
        widget=forms.Select(attrs={
            'class': 'form-select',
            'id': 'id_serology_hep_c',
        }),
        help_text="Hepatitis C virus antibodies enzyme immunoassay (SRS BBMS-F-024)."
    )
    syphilis = forms.ChoiceField(
        choices=CHOICES,
        required=False,
        label="Syphilis (Treponema / VDRL / RPR)",
        widget=forms.Select(attrs={
            'class': 'form-select',
            'id': 'id_serology_syphilis',
        }),
        help_text="Treponema pallidum / non-treponemal serological test (SRS BBMS-F-024)."
    )
    notes = forms.CharField(
        required=False,
        label="Laboratory Notes / Reagent Batch",
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 2,
            'placeholder': 'Optional testing kit lot number, optical density readings, or lab remarks.',
            'id': 'id_serology_notes',
        }),
        help_text="Audit notes recorded with this testing session (SRS BBMS-F-029)."
    )

    def __init__(self, *args, blood_unit=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.blood_unit = blood_unit
        if blood_unit and not self.is_bound:
            existing = {t.test_type: t.result for t in blood_unit.serology_tests.all()}
            from .models import SerologyTestType
            if SerologyTestType.HIV in existing:
                self.fields['hiv'].initial = existing[SerologyTestType.HIV]
            if SerologyTestType.HEPATITIS_B in existing:
                self.fields['hepatitis_b'].initial = existing[SerologyTestType.HEPATITIS_B]
            if SerologyTestType.HEPATITIS_C in existing:
                self.fields['hepatitis_c'].initial = existing[SerologyTestType.HEPATITIS_C]
            if SerologyTestType.SYPHILIS in existing:
                self.fields['syphilis'].initial = existing[SerologyTestType.SYPHILIS]

    def save(self, blood_unit, staff_user=None):
        """
        Records the entered serology results on the blood unit and evaluates status.
        """
        from .models import SerologyTestType
        data = self.cleaned_data
        panel = {}
        if data.get('hiv'):
            panel[SerologyTestType.HIV] = data['hiv']
        if data.get('hepatitis_b'):
            panel[SerologyTestType.HEPATITIS_B] = data['hepatitis_b']
        if data.get('hepatitis_c'):
            panel[SerologyTestType.HEPATITIS_C] = data['hepatitis_c']
        if data.get('syphilis'):
            panel[SerologyTestType.SYPHILIS] = data['syphilis']

        notes = data.get('notes', '')
        blood_unit.record_serology_panel(panel, staff_user=staff_user, notes=notes)
        return blood_unit


