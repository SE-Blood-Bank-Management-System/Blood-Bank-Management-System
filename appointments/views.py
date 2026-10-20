from django.shortcuts import render
from accounts.models import User
from accounts.rbac import role_required


@role_required(User.Role.DONOR, User.Role.STAFF, User.Role.ADMIN)
def appointment_list(request):
    """
    List user appointments with options to reschedule/cancel.
    SRS: 4.4 (BBMS-F-014, BBMS-F-015), 5.1.2 (BBMS-SR-003)
    """
    context = {
        'title': 'My Appointments',
        'appointments': [],
    }
    return render(request, 'appointments/list.html', context)


@role_required(User.Role.DONOR, User.Role.ADMIN)
def book_appointment(request):
    """
    Book a donation appointment selecting date, time slot, and blood bank location.
    SRS: 4.4 (BBMS-F-012), 5.1.2 (BBMS-SR-003)
    """
    locations = [
        {'id': 1, 'name': 'Central City Blood Bank', 'address': '101 Healthcare Blvd'},
        {'id': 2, 'name': 'Metro Memorial Blood Center', 'address': '45 Red Cross Way'},
        {'id': 3, 'name': 'University Hospital Blood Donation Wing', 'address': '12 Campus Road'},
    ]
    slots = ['09:00 AM - 10:00 AM', '10:00 AM - 11:00 AM', '11:00 AM - 12:00 PM', '02:00 PM - 03:00 PM', '03:00 PM - 04:00 PM']
    context = {
        'title': 'Book Donation Appointment',
        'locations': locations,
        'slots': slots,
    }
    return render(request, 'appointments/book.html', context)
