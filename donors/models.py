from django.conf import settings
from django.db import models


QUESTIONNAIRE_QUESTIONS = [
    {
        'name': 'feeling_well',
        'label': 'Are you feeling well and in good health today?',
        'eligible_answer': 'yes',
        'disqualify_reason': 'You must be feeling well and in good health on the day of donation.',
        'aliases': ['feeling_well_today', 'q1'],
    },
    {
        'name': 'recent_fever',
        'label': 'Have you had a fever or illness in the last 48 hours?',
        'eligible_answer': 'no',
        'disqualify_reason': 'Recent fever or illness in the last 48 hours.',
        'aliases': ['fever_illness', 'recent_fever_illness', 'q2'],
    },
    {
        'name': 'antibiotics',
        'label': 'Have you taken antibiotics in the past 7 days?',
        'eligible_answer': 'no',
        'disqualify_reason': 'Antibiotics taken within the past 7 days requires a waiting period.',
        'aliases': ['antibiotics_past_7_days', 'q3'],
    },
    {
        'name': 'tattoo_piercing',
        'label': 'Have you had a tattoo or body piercing in the last 6 months?',
        'eligible_answer': 'no',
        'disqualify_reason': 'Tattoo or piercing received in the last 6 months requires a deferral period.',
        'aliases': ['tattoo_or_piercing', 'q4'],
    },
    {
        'name': 'malaria_travel',
        'label': 'Have you traveled to a malaria-endemic zone in the last 12 months?',
        'eligible_answer': 'no',
        'disqualify_reason': 'Recent travel to a malaria-endemic zone requires a deferral period.',
        'aliases': ['travel_malaria', 'malaria_endemic_travel', 'q5'],
    },
    {
        'name': 'pregnancy',
        'label': 'Are you currently pregnant or have you given birth in the past 6 months?',
        'eligible_answer': 'no',
        'disqualify_reason': 'Pregnancy or childbirth within the past 6 months temporarily defers donation.',
        'aliases': ['is_pregnant', 'pregnant', 'q6'],
    },
    {
        'name': 'chronic_blood_conditions',
        'label': 'Do you have a history of chronic blood conditions, bleeding disorders, or cardiovascular disease?',
        'eligible_answer': 'no',
        'disqualify_reason': 'History of chronic blood conditions or bleeding disorders.',
        'aliases': ['chronic_conditions', 'blood_conditions', 'q7'],
    },
]


class MedicalEligibilityResponse(models.Model):
    """
    Stores donor medical eligibility screening responses, pass/fail outcome,
    reasons for ineligibility, and audit timestamps.
    SRS: BBMS-F-009, BBMS-F-010, BBMS-F-011.
    """
    class Status(models.TextChoices):
        ELIGIBLE = 'Eligible', 'Eligible'
        INELIGIBLE = 'Ineligible', 'Ineligible'

    donor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='eligibility_responses',
        help_text='The donor who completed the screening'
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.ELIGIBLE,
        help_text='Eligibility evaluation outcome'
    )
    responses = models.JSONField(
        default=dict,
        help_text='Audit log of questions and answers submitted by donor'
    )
    ineligibility_reason = models.TextField(
        blank=True,
        help_text='Explanatory reason(s) if donor is evaluated as ineligible'
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        help_text='Timestamp when the questionnaire was submitted'
    )
    updated_at = models.DateTimeField(
        auto_now=True
    )

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Medical Eligibility Response'
        verbose_name_plural = 'Medical Eligibility Responses'

    @property
    def is_eligible(self):
        return self.status in (self.Status.ELIGIBLE, 'Eligible', 'ELIGIBLE')

    @property
    def reason(self):
        return self.ineligibility_reason

    @property
    def reasons(self):
        return self.ineligibility_reason

    def __str__(self):
        return f"{self.donor.username} - {self.status} ({self.created_at.strftime('%Y-%m-%d %H:%M')})"


# Convenience aliases
EligibilityResponse = MedicalEligibilityResponse
EligibilityCheck = MedicalEligibilityResponse


def is_eligible(donor_user):
    """
    Helper function to verify if a donor has passed eligibility screening.
    SRS: BBMS-F-009 to BBMS-F-011.
    """
    if not donor_user or not donor_user.is_authenticated:
        return False
    latest = MedicalEligibilityResponse.objects.filter(donor=donor_user).order_by('-created_at').first()
    return latest is not None and latest.is_eligible
