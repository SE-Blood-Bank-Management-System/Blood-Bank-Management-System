from django.shortcuts import render
from accounts.models import User
from accounts.rbac import role_required


@role_required(User.Role.DONOR, User.Role.ADMIN)
def dashboard(request):
    """
    Donor Dashboard (SRS 4.2: BBMS-F-006 to BBMS-F-008).
    Accessible by Donors and Administrators.
    """
    context = {
        'title': 'Donor Dashboard',
        'donor': request.user,
        'next_eligible_date': 'Available now (No prior donations recorded)',
        'total_donations': 0,
        'recent_donations': [],
    }
    return render(request, 'donors/dashboard.html', context)


@role_required(User.Role.DONOR, User.Role.ADMIN)
def donation_history(request):
    """
    View donation history including Bag IDs, dates, and locations (SRS 4.2: BBMS-F-007).
    """
    context = {
        'title': 'Donation History',
        'donations': [],
    }
    return render(request, 'donors/history.html', context)


@role_required(User.Role.DONOR, User.Role.ADMIN)
def eligibility_check(request):
    """
    Medical eligibility questionnaire skeleton (SRS 4.3: BBMS-F-009, BBMS-F-010).
    """
    context = {
        'title': 'Medical Eligibility Screening',
    }
    return render(request, 'donors/eligibility.html', context)
