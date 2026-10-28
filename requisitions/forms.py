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
