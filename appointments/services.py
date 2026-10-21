import logging
from datetime import date, datetime, time, timedelta
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from accounts.models import User
from .models import Appointment, AppointmentSlot, BloodBankLocation

logger = logging.getLogger(__name__)

DEFAULT_LOCATIONS_DATA = [
    {
        'id': 1,
        'name': 'Central City Blood Bank',
        'address': '101 Healthcare Blvd',
        'city': 'Central City',
        'contact_number': '(555) 010-1001',
        'contact_email': 'central@bloodbank.org',
    },
    {
        'id': 2,
        'name': 'Metro Memorial Blood Center',
        'address': '45 Red Cross Way',
        'city': 'Metro City',
        'contact_number': '(555) 010-1002',
        'contact_email': 'metro@bloodbank.org',
    },
    {
        'id': 3,
        'name': 'University Hospital Blood Donation Wing',
        'address': '12 Campus Road',
        'city': 'Metro City',
        'contact_number': '(555) 010-1003',
        'contact_email': 'unihospital@bloodbank.org',
    },
]

DEFAULT_DAILY_SLOTS = [
    (time(9, 0), time(10, 0)),
    (time(10, 0), time(11, 0)),
    (time(11, 0), time(12, 0)),
    (time(14, 0), time(15, 0)),
    (time(15, 0), time(16, 0)),
]


def ensure_default_locations():
    """
    Ensure the default BloodBankLocation records exist.
    Maintains compatibility with initial UI and SRS locations.
    """
    for data in DEFAULT_LOCATIONS_DATA:
        BloodBankLocation.objects.get_or_create(
            name=data['name'],
            defaults={
                'address': data['address'],
                'city': data['city'],
                'contact_number': data['contact_number'],
                'contact_email': data['contact_email'],
                'is_active': True,
            }
        )
    return BloodBankLocation.objects.filter(is_active=True).order_by('name')


def get_or_create_slots_for_date(location, target_date, default_capacity=5):
    """
    Retrieve or initialize the standard time slots for a given location and date.
    SRS: BBMS-F-012, BBMS-F-013.
    """
    existing_slots = AppointmentSlot.objects.filter(
        location=location,
        date=target_date
    ).order_by('start_time')

    if existing_slots.exists():
        return list(existing_slots)

    # Automatically generate default daily slots if not already configured
    created_slots = []
    with transaction.atomic():
        for start_t, end_t in DEFAULT_DAILY_SLOTS:
            slot, _ = AppointmentSlot.objects.get_or_create(
                location=location,
                date=target_date,
                start_time=start_t,
                defaults={
                    'end_time': end_t,
                    'max_capacity': default_capacity,
                    'is_active': True,
                }
            )
            created_slots.append(slot)
    return created_slots


def get_available_slots_data(location_id=None, target_date=None):
    """
    Return slot status data dictionary for calendar or AJAX / REST APIs.
    SRS: BBMS-F-012, BBMS-F-013, SAD 4.3.
    """
    ensure_default_locations()
    if not target_date:
        target_date = timezone.localdate() + timedelta(days=1)
    elif isinstance(target_date, str):
        target_date = date.fromisoformat(target_date)

    locations_qs = BloodBankLocation.objects.filter(is_active=True)
    if location_id:
        locations_qs = locations_qs.filter(id=location_id)

    results = []
    now = timezone.now()

    for loc in locations_qs:
        slots = get_or_create_slots_for_date(loc, target_date)
        for s in slots:
            booked = s.booked_count
            available_cap = max(0, s.max_capacity - booked)
            is_avail = s.is_available(current_dt=now)

            results.append({
                'slot_id': s.id,
                'location_id': loc.id,
                'location_name': loc.name,
                'address': loc.address,
                'city': loc.city,
                'date': target_date.isoformat(),
                'start_time': s.start_time.strftime('%H:%M'),
                'end_time': s.end_time.strftime('%H:%M'),
                'time_label': s.time_label,
                'max_capacity': s.max_capacity,
                'booked_count': booked,
                'available_capacity': available_cap,
                'is_full': s.is_full,
                'is_available': is_avail,
            })
    return results


def book_appointment_slot(donor, slot, donor_notes='', request=None):
    """
    Reserve an appointment slot for an eligible authenticated donor with atomic locking.
    SRS References:
    - BBMS-F-009 to BBMS-F-011: Pre-requisite Medical Eligibility Screening
    - BBMS-F-012: Select date, time slot, location
    - BBMS-F-013: Prevent overbooking / capacity enforcement
    - BBMS-F-016: Send/record confirmation notification
    """
    if not donor or not donor.is_authenticated:
        raise ValidationError("Authentication required to book an appointment.")

    # Only DONOR or ADMIN role permitted
    if not (donor.role in [User.Role.DONOR, User.Role.ADMIN] or donor.is_superuser):
        raise ValidationError("Only registered donors are authorized to book donation appointments.")

    # Medical eligibility screening check (SRS BBMS-F-009, BBMS-F-012)
    # Admin is exempt or donor must have passed screening
    is_eligible_donor = donor.is_administrator or getattr(donor, 'is_eligible', False)
    if not is_eligible_donor:
        raise ValidationError(
            "Medical eligibility screening required: You must complete and pass the "
            "Medical Eligibility Questionnaire before booking an appointment (SRS BBMS-F-009)."
        )

    # Enforce atomic transaction and row locking on AppointmentSlot to prevent overbooking
    with transaction.atomic():
        locked_slot = AppointmentSlot.objects.select_for_update().get(id=slot.id)

        # Check future time
        if not locked_slot.is_available():
            if locked_slot.is_full:
                raise ValidationError("This time slot has reached its maximum donor capacity (SRS BBMS-F-013).")
            raise ValidationError("This appointment slot is in the past or currently unavailable.")

        # Check if donor already has an active appointment for the exact same slot/day
        existing = Appointment.objects.filter(
            donor=donor,
            slot=locked_slot,
            status__in=[Appointment.Status.SCHEDULED, Appointment.Status.CONFIRMED]
        ).exists()
        if existing:
            raise ValidationError("You already have an active appointment scheduled for this time slot.")

        # Retrieve latest eligibility screening response for audit log (SRS BBMS-F-011)
        latest_eligibility = donor.get_latest_eligibility() if hasattr(donor, 'get_latest_eligibility') else None

        appointment = Appointment.objects.create(
            donor=donor,
            slot=locked_slot,
            location=locked_slot.location,
            date=locked_slot.date,
            time_slot=locked_slot.time_label,
            status=Appointment.Status.CONFIRMED,
            eligibility_check=latest_eligibility,
            donor_notes=donor_notes or '',
        )

        # Trigger confirmation notification record (SRS BBMS-F-016)
        send_appointment_notification(appointment, event_type='BOOKED')

    return appointment


def reschedule_donor_appointment(appointment, new_slot, user):
    """
    Reschedule an existing appointment if outside the 24-hour window (SRS BBMS-F-014, TC-APT-02).
    """
    if not appointment:
        raise ValidationError("Appointment not found.")

    # Authorization guard: must be appointment owner or staff/admin
    if appointment.donor != user and not (user.is_staff_member or user.is_administrator or user.is_superuser):
        raise ValidationError("You do not have permission to reschedule this appointment.")

    if not appointment.can_reschedule():
        raise ValidationError(
            "Rescheduling is only permitted up to 24 hours prior to the scheduled appointment (SRS BBMS-F-014)."
        )

    with transaction.atomic():
        locked_new_slot = AppointmentSlot.objects.select_for_update().get(id=new_slot.id)
        if not locked_new_slot.is_available():
            raise ValidationError("The selected new time slot is full or unavailable (SRS BBMS-F-013).")

        appointment.reschedule(locked_new_slot)
        send_appointment_notification(appointment, event_type='RESCHEDULED')

    return appointment


def cancel_donor_appointment(appointment, user, reason='Cancelled by donor'):
    """
    Cancel an appointment and immediately release slot capacity (SRS BBMS-F-015, TC-APT-01).
    """
    if not appointment:
        raise ValidationError("Appointment not found.")

    if appointment.donor != user and not (user.is_staff_member or user.is_administrator or user.is_superuser):
        raise ValidationError("You do not have permission to cancel this appointment.")

    if not appointment.can_cancel():
        raise ValidationError("This appointment is already cancelled or cannot be cancelled.")

    with transaction.atomic():
        appointment.cancel(reason=reason)
        send_appointment_notification(appointment, event_type='CANCELLED')

    return appointment


def send_appointment_notification(appointment, event_type='BOOKED'):
    """
    Generates and dispatches confirmation notification for appointment lifecycle events.
    SRS BBMS-F-016: Send confirmation notification (on-screen / email) when booked, rescheduled, or cancelled.
    """
    subject = f"BBMS Blood Donation Appointment {event_type.title()} - {appointment.booking_reference}"
    message = (
        f"Dear {appointment.donor.get_full_name() or appointment.donor.username},\n\n"
        f"Your blood donation appointment has been {event_type.lower()}.\n"
        f"Booking Reference: {appointment.booking_reference}\n"
        f"Center: {appointment.location.name} ({appointment.location.address})\n"
        f"Date: {appointment.date.strftime('%A, %B %d, %Y')}\n"
        f"Time Slot: {appointment.time_slot}\n"
        f"Status: {appointment.status}\n\n"
        "Thank you for helping save lives!\n"
        "Blood Bank Management System (BBMS)"
    )
    logger.info("Appointment Notification [%s]: %s -> %s", event_type, appointment.booking_reference, appointment.donor.email)
    return {'subject': subject, 'message': message}
