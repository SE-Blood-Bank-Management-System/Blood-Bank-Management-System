from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone

from .models import AppointmentSlot, BloodBankLocation
from .services import get_or_create_slots_for_date


class AppointmentBookingForm(forms.Form):
    """
    Form for donors to select location, date, and available time slot.
    SRS: BBMS-F-012, BBMS-F-013.
    """
    location = forms.ModelChoiceField(
        queryset=BloodBankLocation.objects.filter(is_active=True),
        empty_label="-- Select Blood Bank Location --",
        widget=forms.Select(attrs={'class': 'form-select', 'id': 'id_location'}),
        help_text="Donation center where you will give blood"
    )
    date = forms.DateField(
        widget=forms.DateInput(attrs={
            'type': 'date',
            'class': 'form-control',
            'id': 'id_date'
        }),
        help_text="Scheduled donation date"
    )
    slot_id = forms.IntegerField(
        required=False,
        widget=forms.HiddenInput(attrs={'id': 'id_slot_id'})
    )
    slot = forms.CharField(
        required=False,
        widget=forms.Select(attrs={'class': 'form-select', 'id': 'id_slot'}),
        help_text="Select an available time slot"
    )
    donor_notes = forms.CharField(
        required=False,
        max_length=500,
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 2,
            'placeholder': 'Optional: Note any special assistance requirements or inquiries'
        })
    )

    def clean_date(self):
        booking_date = self.cleaned_data.get('date')
        if not booking_date:
            raise ValidationError("Please provide a donation date.")
        today = timezone.localdate()
        if booking_date < today:
            raise ValidationError("Appointment date cannot be in the past.")
        return booking_date

    def clean(self):
        cleaned_data = super().clean()
        location = cleaned_data.get('location')
        booking_date = cleaned_data.get('date')
        slot_id = cleaned_data.get('slot_id')
        slot_label = cleaned_data.get('slot')

        if not location or not booking_date:
            return cleaned_data

        target_slot = None
        if slot_id:
            try:
                target_slot = AppointmentSlot.objects.get(id=slot_id, location=location, date=booking_date)
            except AppointmentSlot.DoesNotExist:
                raise ValidationError("The selected appointment slot could not be found.")
        elif slot_label:
            # Match slot by time_label or string e.g. "09:00 AM - 10:00 AM"
            slots = get_or_create_slots_for_date(location, booking_date)
            for s in slots:
                if s.time_label == slot_label or slot_label in s.time_label:
                    target_slot = s
                    break
            if not target_slot:
                raise ValidationError(f"Invalid time slot selected: {slot_label}")
        else:
            raise ValidationError("Please select a time slot.")

        # Check availability and capacity (SRS BBMS-F-013)
        if not target_slot.is_available():
            if target_slot.is_full:
                raise ValidationError(
                    f"The time slot '{target_slot.time_label}' has reached maximum capacity "
                    f"({target_slot.max_capacity}/{target_slot.max_capacity}). Please choose another slot."
                )
            raise ValidationError("The selected time slot is currently unavailable or in the past.")

        cleaned_data['selected_slot'] = target_slot
        return cleaned_data


class AppointmentRescheduleForm(forms.Form):
    """
    Form to reschedule an existing appointment to a new slot.
    SRS: BBMS-F-014 (up to 24 hours before scheduled time).
    """
    location = forms.ModelChoiceField(
        queryset=BloodBankLocation.objects.filter(is_active=True),
        widget=forms.Select(attrs={'class': 'form-select'}),
        help_text="Center for rescheduled appointment"
    )
    date = forms.DateField(
        widget=forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
        help_text="New appointment date"
    )
    slot_id = forms.IntegerField(
        widget=forms.HiddenInput()
    )

    def __init__(self, appointment=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.appointment = appointment

    def clean_date(self):
        new_date = self.cleaned_data.get('date')
        if new_date and new_date < timezone.localdate():
            raise ValidationError("New appointment date cannot be in the past.")
        return new_date

    def clean(self):
        cleaned_data = super().clean()
        if self.appointment and not self.appointment.can_reschedule():
            raise ValidationError(
                "Rescheduling is blocked inside the 24-hour window before the appointment (SRS BBMS-F-014)."
            )

        slot_id = cleaned_data.get('slot_id')
        if slot_id:
            try:
                new_slot = AppointmentSlot.objects.get(id=slot_id)
                if not new_slot.is_available():
                    raise ValidationError("The selected replacement slot is not available or full.")
                cleaned_data['new_slot'] = new_slot
            except AppointmentSlot.DoesNotExist:
                raise ValidationError("Selected slot not found.")
        return cleaned_data


class AppointmentCancelForm(forms.Form):
    """
    Form to record cancellation reason and release slot capacity.
    SRS: BBMS-F-015.
    """
    reason = forms.CharField(
        required=False,
        max_length=300,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Optional: Reason for cancellation'
        })
    )
