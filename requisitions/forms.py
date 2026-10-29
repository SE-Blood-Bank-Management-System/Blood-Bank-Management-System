from django import forms
from django.utils import timezone

from .models import Requisition


class RequisitionForm(forms.ModelForm):
    class Meta:
        model = Requisition
        fields = ['blood_group', 'component_type', 'quantity', 'required_by', 'is_stat']
        labels = {'is_stat': 'Emergency / STAT request', 'required_by': 'Required by'}
        widgets = {'required_by': forms.DateInput(attrs={'type': 'date'}),
                   'quantity': forms.NumberInput(attrs={'min': 1})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            field.widget.attrs['class'] = 'form-check-input' if name == 'is_stat' else 'form-control'
        self.fields['required_by'].widget.attrs['min'] = timezone.localdate().isoformat()
        self.fields['is_stat'].help_text = 'Use for urgent clinical requests. Safety checks and staff approval still apply.'

    def clean_required_by(self):
        value = self.cleaned_data['required_by']
        if value < timezone.localdate():
            raise forms.ValidationError('Required-by date cannot be in the past.')
        return value


class ReviewForm(forms.Form):
    action = forms.ChoiceField(choices=[('approve', 'Approve'), ('reject', 'Reject')],
                               widget=forms.Select(attrs={'class': 'form-select'}))
    reason = forms.CharField(required=False, label='Review note / rejection reason',
                             widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
                             help_text='A reason is required when rejecting a request.')
    version = forms.IntegerField(min_value=0, widget=forms.HiddenInput)

    def clean(self):
        data = super().clean()
        if data.get('action') == 'reject' and not data.get('reason'):
            self.add_error('reason', 'A rejection reason is required.')
        return data


class PriorityForm(forms.Form):
    is_stat = forms.BooleanField(required=False, label='Emergency / STAT',
                                 widget=forms.CheckboxInput(attrs={'class': 'form-check-input'}))
    version = forms.IntegerField(min_value=0, widget=forms.HiddenInput)


class ReceiptForm(forms.Form):
    bag_ids = forms.MultipleChoiceField(
        label='Bags received', widget=forms.CheckboxSelectMultiple, choices=[],
    )
    version = forms.IntegerField(min_value=0, widget=forms.HiddenInput)

    def __init__(self, *args, deliveries, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['bag_ids'].choices = [
            (item.blood_unit.bag_id, item.blood_unit.bag_id) for item in deliveries
            if item.blood_unit.status == 'Dispatched' and not hasattr(item, 'delivery_confirmation')
        ]


class CrossMatchForm(forms.Form):
    """
    Staff form to record cross-matching and clinical overrides (SRS BBMS-F-049, BBMS-F-050).
    """
    bag_id = forms.CharField(
        max_length=32,
        label='Unit Bag ID',
        widget=forms.TextInput(attrs={
            'class': 'form-control font-monospace',
            'placeholder': 'e.g. BAG-20261028-A1B2C3',
            'id': 'id_cross_match_bag_id',
        }),
        help_text='Scan or enter the Bag ID of the candidate unit to cross-match (SRS BBMS-F-020, BBMS-F-049).'
    )
    override_reason = forms.CharField(
        required=False,
        label='Clinical Override Justification',
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 2,
            'placeholder': (
                'Mandatory if unit is incompatible (e.g. Emergency extreme '
                'uncrossmatched protocol, clinician authorization).'
            ),
            'id': 'id_override_reason',
        }),
        help_text='Required when cross-matching an incompatible blood unit (SRS BBMS-F-050).'
    )
    version = forms.IntegerField(min_value=0, widget=forms.HiddenInput, required=False)

    def clean_bag_id(self):
        bag_id = self.cleaned_data.get('bag_id', '').strip()
        if not bag_id:
            raise forms.ValidationError('Please provide a blood unit Bag ID.')
        return bag_id

