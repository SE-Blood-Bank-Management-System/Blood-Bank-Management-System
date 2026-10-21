from datetime import datetime, time, timedelta
import uuid
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class BloodBankLocation(models.Model):
    """
    Blood donation center / bank location.
    SRS: 4.4 (BBMS-F-012)
    """
    name = models.CharField(max_length=150, unique=True, help_text="Donation center name")
    address = models.CharField(max_length=255, help_text="Physical street address")
    city = models.CharField(max_length=100, default="Central City")
    state = models.CharField(max_length=100, default="State")
    contact_number = models.CharField(max_length=20, blank=True)
    contact_email = models.EmailField(blank=True)
    is_active = models.BooleanField(default=True, help_text="Whether this center accepts appointments")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']
        verbose_name = 'Blood Bank Location'
        verbose_name_plural = 'Blood Bank Locations'

    def __str__(self):
        return f"{self.name} ({self.city})"


class AppointmentSlot(models.Model):
    """
    Time slot available for blood donation appointments on a given date and location.
    Enforces maximum donor capacity per slot (SRS: BBMS-F-012, BBMS-F-013).
    """
    DEFAULT_SLOT_TIMES = [
        (time(9, 0), time(10, 0), '09:00 AM - 10:00 AM'),
        (time(10, 0), time(11, 0), '10:00 AM - 11:00 AM'),
        (time(11, 0), time(12, 0), '11:00 AM - 12:00 PM'),
        (time(14, 0), time(15, 0), '02:00 PM - 03:00 PM'),
        (time(15, 0), time(16, 0), '03:00 PM - 04:00 PM'),
    ]

    location = models.ForeignKey(
        BloodBankLocation,
        on_delete=models.CASCADE,
        related_name='slots',
        help_text="Donation center hosting this slot"
    )
    date = models.DateField(db_index=True, help_text="Date of the appointment slot")
    start_time = models.TimeField(help_text="Slot start time")
    end_time = models.TimeField(help_text="Slot end time")
    max_capacity = models.PositiveIntegerField(
        default=5,
        help_text="Maximum donor appointments that can be booked for this slot (SRS BBMS-F-013)"
    )
    is_active = models.BooleanField(default=True, help_text="Availability flag for this slot")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['date', 'start_time']
        constraints = [
            models.UniqueConstraint(
                fields=['location', 'date', 'start_time'],
                name='unique_location_date_slot'
            )
        ]
        verbose_name = 'Appointment Slot'
        verbose_name_plural = 'Appointment Slots'

    @property
    def time_label(self):
        """Format friendly string e.g. '09:00 AM - 10:00 AM'"""
        return f"{self.start_time.strftime('%I:%M %p')} - {self.end_time.strftime('%I:%M %p')}"

    @property
    def booked_count(self):
        """Active booked appointments count for this slot"""
        return self.appointments.filter(
            status__in=['SCHEDULED', 'CONFIRMED']
        ).count()

    @property
    def available_capacity(self):
        """Remaining capacity for this slot (SRS BBMS-F-013)"""
        return max(0, self.max_capacity - self.booked_count)

    @property
    def is_full(self):
        """True if the slot has reached its configured donor capacity"""
        return self.booked_count >= self.max_capacity

    def is_available(self, current_dt=None):
        """
        Check if the slot is open, has capacity, and is in the future.
        """
        if not self.is_active or self.is_full:
            return False
        if current_dt is None:
            current_dt = timezone.now()
        combined = datetime.combine(self.date, self.start_time)
        slot_dt = timezone.make_aware(combined) if timezone.is_aware(current_dt) else combined
        return slot_dt > current_dt

    def __str__(self):
        return f"{self.location.name} - {self.date} ({self.time_label}) [{self.booked_count}/{self.max_capacity}]"


class Appointment(models.Model):
    """
    Donation appointment booked by an eligible donor.
    SRS: 4.4 (BBMS-F-012 to BBMS-F-016), 5.1.2 (BBMS-SR-003)
    """
    class Status(models.TextChoices):
        SCHEDULED = 'SCHEDULED', 'Scheduled'
        CONFIRMED = 'CONFIRMED', 'Confirmed'
        COMPLETED = 'COMPLETED', 'Completed'
        CANCELLED = 'CANCELLED', 'Cancelled'
        RESCHEDULED = 'RESCHEDULED', 'Rescheduled'

    booking_reference = models.CharField(
        max_length=20,
        unique=True,
        editable=False,
        help_text="Unique human-readable appointment reference code"
    )
    donor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='appointments',
        help_text="The authenticated donor who made this booking"
    )
    slot = models.ForeignKey(
        AppointmentSlot,
        on_delete=models.PROTECT,
        related_name='appointments',
        help_text="The reserved time slot"
    )
    location = models.ForeignKey(
        BloodBankLocation,
        on_delete=models.PROTECT,
        related_name='appointments',
        help_text="The donation center location"
    )
    date = models.DateField(db_index=True, help_text="Appointment date")
    time_slot = models.CharField(max_length=60, help_text="Time window label for audit and reference")
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.CONFIRMED,
        help_text="Current lifecycle state of the appointment"
    )
    eligibility_check = models.ForeignKey(
        'donors.MedicalEligibilityResponse',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='appointments',
        help_text="Associated eligibility questionnaire response for audit (SRS BBMS-F-011)"
    )
    donor_notes = models.TextField(blank=True, help_text="Optional donor special requests or notes")
    cancellation_reason = models.TextField(blank=True, help_text="Reason for cancellation if cancelled")
    cancelled_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-date', '-created_at']
        verbose_name = 'Donation Appointment'
        verbose_name_plural = 'Donation Appointments'

    def save(self, *args, **kwargs):
        if not self.booking_reference:
            self.booking_reference = f"APT-{uuid.uuid4().hex[:8].upper()}"
        if self.slot:
            self.location = self.slot.location
            self.date = self.slot.date
            self.time_slot = self.slot.time_label
        super().save(*args, **kwargs)

    @property
    def appointment_datetime(self):
        """Combined aware/naive datetime of the appointment start time"""
        dt = datetime.combine(self.date, self.slot.start_time)
        return timezone.make_aware(dt) if timezone.is_aware(timezone.now()) else dt

    def can_reschedule(self, current_dt=None):
        """
        SRS BBMS-F-014 & TC-APT-02:
        Rescheduling is allowed up to 24 hours before the scheduled time.
        Inside the 24-hour window, rescheduling is blocked.
        """
        if self.status not in [self.Status.SCHEDULED, self.Status.CONFIRMED]:
            return False
        if current_dt is None:
            current_dt = timezone.now()
        diff = self.appointment_datetime - current_dt
        return diff >= timedelta(hours=24)

    def can_cancel(self, current_dt=None):
        """
        SRS BBMS-F-015 & TC-APT-01:
        Cancellation is allowed for scheduled or confirmed appointments.
        """
        return self.status in [self.Status.SCHEDULED, self.Status.CONFIRMED]

    def cancel(self, reason='Cancelled by donor'):
        """
        Cancel the appointment and immediately release slot capacity (SRS BBMS-F-015).
        """
        if not self.can_cancel():
            raise ValidationError("This appointment cannot be cancelled.")
        self.status = self.Status.CANCELLED
        self.cancellation_reason = reason
        self.cancelled_at = timezone.now()
        self.save(update_fields=['status', 'cancellation_reason', 'cancelled_at', 'updated_at'])

    def reschedule(self, new_slot, current_dt=None):
        """
        Reschedule the appointment to a new slot if eligible and outside 24h window (SRS BBMS-F-014).
        """
        if not self.can_reschedule(current_dt=current_dt):
            raise ValidationError("Appointments cannot be rescheduled within 24 hours of scheduled time (SRS BBMS-F-014).")
        if not new_slot.is_available(current_dt=current_dt):
            raise ValidationError("The selected time slot is full or unavailable (SRS BBMS-F-013).")

        self.slot = new_slot
        self.location = new_slot.location
        self.date = new_slot.date
        self.time_slot = new_slot.time_label
        self.status = self.Status.CONFIRMED
        self.save(update_fields=['slot', 'location', 'date', 'time_slot', 'status', 'updated_at'])

    def __str__(self):
        return f"{self.booking_reference}: {self.donor.username} @ {self.location.name} on {self.date} ({self.time_slot})"
