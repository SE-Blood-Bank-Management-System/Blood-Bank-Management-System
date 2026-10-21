"""
Views for Appointment scheduling, capacity management, rescheduling, and cancellation.
SRS References:
- Section 4.4 (BBMS-F-012): Date, Time Slot, and Center Booking
- Section 4.4 (BBMS-F-013): Time Slot Capacity Limit & Overbooking Prevention
- Section 4.4 (BBMS-F-014): 24-Hour Rescheduling Boundary
- Section 4.4 (BBMS-F-015): Cancellation & Slot Capacity Release
- Section 4.4 (BBMS-F-016): Confirmation Notifications
- Section 5.1.2 (BBMS-SR-003): Server-Side RBAC Enforcement
SAD Reference:
- Section 4.3: REST API (POST /api/appointments, PATCH /api/appointments/{id})
"""
import json
from datetime import date, timedelta
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.http import HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from accounts.models import User
from accounts.rbac import _is_api_request, role_required
from .forms import AppointmentBookingForm, AppointmentCancelForm, AppointmentRescheduleForm
from .models import Appointment, AppointmentSlot, BloodBankLocation
from .services import (
    book_appointment_slot,
    cancel_donor_appointment,
    ensure_default_locations,
    get_available_slots_data,
    get_or_create_slots_for_date,
    reschedule_donor_appointment,
)


@role_required(User.Role.DONOR, User.Role.STAFF, User.Role.ADMIN)
def appointment_list(request):
    """
    List user appointments with options to reschedule/cancel.
    Donors view their own appointments; Staff/Admin can view all appointments.
    SRS: 4.4 (BBMS-F-014, BBMS-F-015), 5.1.2 (BBMS-SR-003)
    """
    ensure_default_locations()
    if request.user.role == User.Role.DONOR and not (request.user.is_staff_member or request.user.is_administrator):
        appointments_qs = Appointment.objects.filter(donor=request.user)
    else:
        appointments_qs = Appointment.objects.all()

    appointments = appointments_qs.select_related('location', 'slot', 'donor').order_by('-date', '-created_at')

    # Categorize upcoming vs past/cancelled
    now = timezone.now()
    today = timezone.localdate()

    context = {
        'title': 'My Appointments',
        'appointments': appointments,
        'today': today,
        'now': now,
    }
    return render(request, 'appointments/list.html', context)


@role_required(User.Role.DONOR, User.Role.ADMIN)
def book_appointment(request):
    """
    Book a donation appointment selecting date, time slot, and blood bank location.
    Requires passing medical eligibility questionnaire (SRS BBMS-F-009, BBMS-F-012).
    Enforces maximum slot capacity with atomic locking (SRS BBMS-F-013).
    """
    ensure_default_locations()
    locations = BloodBankLocation.objects.filter(is_active=True).order_by('name')

    default_slots_labels = [
        '09:00 AM - 10:00 AM',
        '10:00 AM - 11:00 AM',
        '11:00 AM - 12:00 PM',
        '02:00 PM - 03:00 PM',
        '03:00 PM - 04:00 PM',
    ]

    is_donor_eligible = request.user.is_administrator or getattr(request.user, 'is_eligible', False)
    min_date = (timezone.localdate() + timedelta(days=1)).isoformat()
    max_date = (timezone.localdate() + timedelta(days=60)).isoformat()

    if request.method == 'POST':
        # API request parsing if application/json
        if request.content_type == 'application/json':
            return api_appointments(request)

        form = AppointmentBookingForm(request.POST)

        # Eligibility check
        if not is_donor_eligible:
            messages.error(
                request,
                "Medical eligibility screening required: You must complete and pass the "
                "Medical Eligibility Questionnaire before booking an appointment (SRS BBMS-F-009)."
            )
            return redirect('donors:eligibility')

        if form.is_valid():
            selected_slot = form.cleaned_data['selected_slot']
            donor_notes = form.cleaned_data.get('donor_notes', '')

            try:
                appointment = book_appointment_slot(
                    donor=request.user,
                    slot=selected_slot,
                    donor_notes=donor_notes,
                    request=request
                )
                messages.success(
                    request,
                    f"Appointment booked successfully! Reference: {appointment.booking_reference}. "
                    f"We look forward to seeing you at {appointment.location.name} on {appointment.date}."
                )
                return redirect('appointments:detail', pk=appointment.pk)
            except ValidationError as e:
                for msg in e.messages if hasattr(e, 'messages') else [str(e)]:
                    messages.error(request, msg)
            except Exception as e:
                messages.error(request, f"Unable to confirm booking: {str(e)}")
        else:
            for field, errors in form.errors.items():
                for err in errors:
                    messages.error(request, err if field == '__all__' else f"{field.title()}: {err}")

    else:
        initial_loc = locations.first()
        initial_date = timezone.localdate() + timedelta(days=1)
        form = AppointmentBookingForm(initial={
            'location': initial_loc,
            'date': initial_date,
        })

    # Prepare available slots data for the initial/selected date
    initial_location = locations.first()
    tomorrow = timezone.localdate() + timedelta(days=1)
    slots_data = get_available_slots_data(
        location_id=initial_location.id if initial_location else None,
        target_date=tomorrow
    )

    context = {
        'title': 'Book Donation Appointment',
        'form': form,
        'locations': locations,
        'slots': default_slots_labels,
        'slots_data': slots_data,
        'is_eligible': is_donor_eligible,
        'min_date': min_date,
        'max_date': max_date,
    }
    return render(request, 'appointments/book.html', context)


@role_required(User.Role.DONOR, User.Role.STAFF, User.Role.ADMIN)
def appointment_detail(request, pk):
    """
    View details of an individual appointment.
    Enforces authorization: Donors can only view their own appointments (SRS 5.1.2).
    """
    appointment = get_object_or_404(Appointment.objects.select_related('location', 'slot', 'donor'), pk=pk)

    # Permission check: A donor cannot view another donor's appointments
    if request.user.role == User.Role.DONOR and not (request.user.is_staff_member or request.user.is_administrator):
        if appointment.donor != request.user:
            return HttpResponseForbidden("Access Denied: You are not authorized to view another donor's appointment.")

    context = {
        'title': f'Appointment {appointment.booking_reference}',
        'appointment': appointment,
        'can_reschedule': appointment.can_reschedule(),
        'can_cancel': appointment.can_cancel(),
    }
    return render(request, 'appointments/detail.html', context)


@role_required(User.Role.DONOR, User.Role.STAFF, User.Role.ADMIN)
def reschedule_appointment(request, pk):
    """
    Reschedule an existing appointment to another available slot.
    Allowed up to 24 hours before the scheduled time; blocked within 24 hours (SRS BBMS-F-014, TC-APT-02).
    """
    appointment = get_object_or_404(Appointment, pk=pk)

    if request.user.role == User.Role.DONOR and not (request.user.is_staff_member or request.user.is_administrator):
        if appointment.donor != request.user:
            return HttpResponseForbidden("Access Denied: You cannot reschedule another donor's appointment.")

    if not appointment.can_reschedule():
        messages.error(
            request,
            "Rescheduling is strictly blocked within 24 hours of scheduled appointment time (SRS BBMS-F-014)."
        )
        return redirect('appointments:detail', pk=appointment.pk)

    locations = BloodBankLocation.objects.filter(is_active=True).order_by('name')
    min_date = (timezone.localdate() + timedelta(days=1)).isoformat()

    if request.method == 'POST':
        form = AppointmentRescheduleForm(appointment=appointment, data=request.POST)
        if form.is_valid():
            new_slot = form.cleaned_data['new_slot']
            try:
                reschedule_donor_appointment(appointment, new_slot, request.user)
                messages.success(
                    request,
                    f"Appointment successfully rescheduled to {appointment.date} at {appointment.time_slot}."
                )
                return redirect('appointments:detail', pk=appointment.pk)
            except ValidationError as e:
                for msg in (e.messages if hasattr(e, 'messages') else [str(e)]):
                    messages.error(request, msg)
        else:
            for field, errors in form.errors.items():
                for err in errors:
                    messages.error(request, err if field == '__all__' else f"{field.title()}: {err}")
    else:
        form = AppointmentRescheduleForm(
            appointment=appointment,
            initial={
                'location': appointment.location,
                'date': appointment.date + timedelta(days=1),
            }
        )

    context = {
        'title': f'Reschedule Appointment {appointment.booking_reference}',
        'appointment': appointment,
        'form': form,
        'locations': locations,
        'min_date': min_date,
    }
    return render(request, 'appointments/reschedule.html', context)


@role_required(User.Role.DONOR, User.Role.STAFF, User.Role.ADMIN)
@require_http_methods(['POST'])
def cancel_appointment(request, pk):
    """
    Cancel an existing appointment and release slot capacity immediately (SRS BBMS-F-015, TC-APT-01).
    """
    appointment = get_object_or_404(Appointment, pk=pk)

    if request.user.role == User.Role.DONOR and not (request.user.is_staff_member or request.user.is_administrator):
        if appointment.donor != request.user:
            return HttpResponseForbidden("Access Denied: You cannot cancel another donor's appointment.")

    if not appointment.can_cancel():
        messages.error(request, "This appointment is already cancelled or cannot be cancelled.")
        return redirect('appointments:detail', pk=appointment.pk)

    reason = request.POST.get('reason', 'Cancelled by donor')
    try:
        cancel_donor_appointment(appointment, request.user, reason=reason)
        messages.success(
            request,
            f"Appointment {appointment.booking_reference} has been cancelled. "
            "Reserved slot capacity has been released."
        )
    except Exception as e:
        messages.error(request, f"Error cancelling appointment: {str(e)}")

    return redirect('appointments:list')


# ---------------------------------------------------------------------------
# REST API Endpoints (SAD Section 4.3: POST /api/appointments, PATCH /api/appointments/{id})
# ---------------------------------------------------------------------------

@require_http_methods(['GET'])
def api_slots(request):
    """
    REST API: GET /api/appointments/slots/?location_id=1&date=YYYY-MM-DD
    Returns available appointment slots with live booked/remaining capacity.
    """
    loc_id = request.GET.get('location_id')
    date_str = request.GET.get('date')

    target_date = None
    if date_str:
        try:
            target_date = date.fromisoformat(date_str)
        except ValueError:
            return JsonResponse({'error': 'Invalid date format. Use YYYY-MM-DD.'}, status=400)

    try:
        data = get_available_slots_data(location_id=loc_id, target_date=target_date)
        return JsonResponse({'slots': data, 'count': len(data)}, status=200)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@role_required(User.Role.DONOR, User.Role.STAFF, User.Role.ADMIN)
@require_http_methods(['GET', 'POST'])
def api_appointments(request):
    """
    REST API:
    - GET /api/appointments/ : List appointments for authenticated user
    - POST /api/appointments/ : Book new appointment (SAD Section 4.3)
    """
    if request.method == 'GET':
        if request.user.role == User.Role.DONOR and not (request.user.is_staff_member or request.user.is_administrator):
            qs = Appointment.objects.filter(donor=request.user)
        else:
            qs = Appointment.objects.all()

        results = [
            {
                'id': a.id,
                'booking_reference': a.booking_reference,
                'donor_username': a.donor.username,
                'location': a.location.name,
                'date': a.date.isoformat(),
                'time_slot': a.time_slot,
                'status': a.status,
                'created_at': a.created_at.isoformat(),
            }
            for a in qs.select_related('location', 'donor')[:50]
        ]
        return JsonResponse({'appointments': results, 'count': len(results)}, status=200)

    # POST booking
    try:
        body = json.loads(request.body.decode('utf-8'))
    except (ValueError, UnicodeDecodeError):
        return JsonResponse({'error': 'Invalid JSON body.'}, status=400)

    slot_id = body.get('slot_id')
    location_id = body.get('location_id')
    date_val = body.get('date')
    slot_label = body.get('slot')
    notes = body.get('notes', '')

    target_slot = None
    if slot_id:
        target_slot = get_object_or_404(AppointmentSlot, id=slot_id)
    elif location_id and date_val and slot_label:
        loc = get_object_or_404(BloodBankLocation, id=location_id)
        booking_date = date.fromisoformat(date_val)
        slots = get_or_create_slots_for_date(loc, booking_date)
        for s in slots:
            if s.time_label == slot_label:
                target_slot = s
                break
        if not target_slot:
            return JsonResponse({'error': f'Slot {slot_label} not found.'}, status=404)
    else:
        return JsonResponse({'error': 'Must provide slot_id or (location_id, date, slot).'}, status=400)

    # Overbooking check (SRS BBMS-F-013)
    if not target_slot.is_available():
        if target_slot.is_full:
            return JsonResponse(
                {'error': 'Conflict: Time slot has reached its configured donor capacity.', 'code': 'SLOT_FULL'},
                status=409
            )
        return JsonResponse({'error': 'Time slot is currently unavailable or in the past.'}, status=400)

    try:
        appointment = book_appointment_slot(
            donor=request.user,
            slot=target_slot,
            donor_notes=notes,
            request=request
        )
        return JsonResponse({
            'message': 'Appointment booked successfully.',
            'appointment': {
                'id': appointment.id,
                'booking_reference': appointment.booking_reference,
                'location': appointment.location.name,
                'date': appointment.date.isoformat(),
                'time_slot': appointment.time_slot,
                'status': appointment.status,
            }
        }, status=201)
    except ValidationError as e:
        msg = e.messages[0] if hasattr(e, 'messages') else str(e)
        return JsonResponse({'error': msg}, status=400)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@role_required(User.Role.DONOR, User.Role.STAFF, User.Role.ADMIN)
@require_http_methods(['GET', 'PATCH', 'DELETE'])
def api_appointment_detail(request, pk):
    """
    REST API: PATCH /api/appointments/{id}
    Reschedule or cancel an appointment (SAD Section 4.3).
    """
    appointment = get_object_or_404(Appointment, pk=pk)

    # Permission check: Donor can only view/modify their own appointment
    if request.user.role == User.Role.DONOR and not (request.user.is_staff_member or request.user.is_administrator):
        if appointment.donor != request.user:
            return JsonResponse({'error': 'Forbidden: You cannot access another donor\'s appointment.'}, status=403)

    if request.method == 'GET':
        return JsonResponse({
            'id': appointment.id,
            'booking_reference': appointment.booking_reference,
            'donor': appointment.donor.username,
            'location': appointment.location.name,
            'date': appointment.date.isoformat(),
            'time_slot': appointment.time_slot,
            'status': appointment.status,
            'can_reschedule': appointment.can_reschedule(),
            'can_cancel': appointment.can_cancel(),
        })

    if request.method == 'DELETE':
        if not appointment.can_cancel():
            return JsonResponse({'error': 'Appointment cannot be cancelled.'}, status=400)
        cancel_donor_appointment(appointment, request.user)
        return JsonResponse({'message': 'Appointment cancelled and capacity released.'}, status=200)

    # PATCH for reschedule or cancel
    try:
        body = json.loads(request.body.decode('utf-8'))
    except (ValueError, UnicodeDecodeError):
        return JsonResponse({'error': 'Invalid JSON body.'}, status=400)

    action = body.get('action', '').lower()

    if action == 'cancel':
        if not appointment.can_cancel():
            return JsonResponse({'error': 'Appointment cannot be cancelled.'}, status=400)
        reason = body.get('reason', 'Cancelled via API')
        cancel_donor_appointment(appointment, request.user, reason=reason)
        return JsonResponse({'message': 'Appointment cancelled successfully.'}, status=200)

    elif action == 'reschedule':
        if not appointment.can_reschedule():
            return JsonResponse(
                {'error': 'Rescheduling is blocked inside the 24-hour window before the appointment (SRS BBMS-F-014).'},
                status=400
            )
        new_slot_id = body.get('slot_id')
        if not new_slot_id:
            return JsonResponse({'error': 'Must provide slot_id for reschedule.'}, status=400)
        new_slot = get_object_or_404(AppointmentSlot, id=new_slot_id)
        if not new_slot.is_available():
            if new_slot.is_full:
                return JsonResponse({'error': 'Selected replacement slot is full.', 'code': 'SLOT_FULL'}, status=409)
            return JsonResponse({'error': 'Selected slot is unavailable.'}, status=400)

        reschedule_donor_appointment(appointment, new_slot, request.user)
        return JsonResponse({
            'message': 'Appointment rescheduled successfully.',
            'appointment': {
                'id': appointment.id,
                'booking_reference': appointment.booking_reference,
                'date': appointment.date.isoformat(),
                'time_slot': appointment.time_slot,
                'status': appointment.status,
            }
        }, status=200)

    return JsonResponse({'error': "Invalid action. Supported: 'reschedule', 'cancel'."}, status=400)
