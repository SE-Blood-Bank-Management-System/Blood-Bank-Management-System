from django import forms
from .models import QUESTIONNAIRE_QUESTIONS


def normalize_boolean_answer(val):
    if val is None:
        return None
    if isinstance(val, bool):
        return 'yes' if val else 'no'
    val_str = str(val).strip().lower()
    if val_str in ('yes', 'true', '1', 'y', 't'):
        return 'yes'
    if val_str in ('no', 'false', '0', 'n', 'f'):
        return 'no'
    return None


class MedicalEligibilityForm(forms.Form):
    """
    Standardized Medical Eligibility Questionnaire Form (SRS 4.3: BBMS-F-009, BBMS-F-010).
    Captures essential health pre-screening questions and validates donor responses.
    """
    CHOICES = [
        ('yes', 'Yes'),
        ('no', 'No'),
    ]

    feeling_well = forms.ChoiceField(
        label='1. Are you currently feeling well and in good health today?',
        choices=CHOICES,
        widget=forms.RadioSelect,
        required=True,
        error_messages={'required': 'Please answer if you are feeling well and healthy today.'}
    )
    recent_fever = forms.ChoiceField(
        label='2. Have you had a fever, illness, or infection in the last 48 hours?',
        choices=CHOICES,
        widget=forms.RadioSelect,
        required=True,
        error_messages={'required': 'Please answer if you had a fever or illness in the last 48 hours.'}
    )
    antibiotics = forms.ChoiceField(
        label='3. Have you taken any antibiotics medication in the past 7 days?',
        choices=CHOICES,
        widget=forms.RadioSelect,
        required=True,
        error_messages={'required': 'Please answer if you have taken antibiotics in the past 7 days.'}
    )
    tattoo_piercing = forms.ChoiceField(
        label='4. Have you had a tattoo or body piercing in the last 6 months?',
        choices=CHOICES,
        widget=forms.RadioSelect,
        required=True,
        error_messages={'required': 'Please answer if you had a tattoo or piercing in the last 6 months.'}
    )
    malaria_travel = forms.ChoiceField(
        label='5. Have you traveled to a malaria-endemic zone in the last 12 months?',
        choices=CHOICES,
        widget=forms.RadioSelect,
        required=True,
        error_messages={'required': 'Please answer if you have traveled to a malaria-endemic zone.'}
    )
    pregnancy = forms.ChoiceField(
        label='6. Are you currently pregnant or have you given birth within the past 6 months?',
        choices=CHOICES,
        widget=forms.RadioSelect,
        required=True,
        error_messages={'required': 'Please answer regarding pregnancy or childbirth.'}
    )
    chronic_blood_conditions = forms.ChoiceField(
        label='7. Do you have a history of chronic blood conditions, bleeding disorders, or cardiovascular disease?',
        choices=CHOICES,
        widget=forms.RadioSelect,
        required=True,
        error_messages={'required': 'Please answer regarding chronic blood conditions.'}
    )

    def __init__(self, *args, **kwargs):
        data = kwargs.get('data')
        args_list = list(args)
        if data is None and args_list:
            data = args_list[0]
            args_list = args_list[1:]

        if data is not None:
            data_dict = {}
            for k in data:
                if hasattr(data, 'getlist'):
                    vals = data.getlist(k)
                    data_dict[k] = vals[-1] if vals else None
                else:
                    data_dict[k] = data[k]

            for q in QUESTIONNAIRE_QUESTIONS:
                canonical = q['name']
                if canonical not in data_dict or data_dict[canonical] is None or data_dict[canonical] == '':
                    for alias in q.get('aliases', []):
                        if alias in data_dict and data_dict[alias] is not None and data_dict[alias] != '':
                            data_dict[canonical] = data_dict[alias]
                            break
                if canonical in data_dict and data_dict[canonical] is not None:
                    norm = normalize_boolean_answer(data_dict[canonical])
                    if norm is not None:
                        data_dict[canonical] = norm
            kwargs['data'] = data_dict

        super().__init__(*args_list, **kwargs)

    def evaluate(self):
        """
        Evaluate cleaned responses against disqualifying conditions.
        Returns:
            is_eligible (bool)
            reasons (list of str)
            answers (dict)
        """
        if not self.is_valid():
            raise ValueError("Form must be valid before evaluating eligibility.")

        answers = self.cleaned_data
        reasons = []
        is_eligible = True

        for q in QUESTIONNAIRE_QUESTIONS:
            ans = answers.get(q['name'])
            if ans != q['eligible_answer']:
                is_eligible = False
                reasons.append(q['disqualify_reason'])

        return is_eligible, reasons, answers
