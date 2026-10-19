from django.shortcuts import render
from django.contrib.auth.decorators import login_required


@login_required
def dashboard(request):
    """
    Donor Dashboard (SRS 4.2: BBMS-F-006 to BBMS-F-008)
    Displays profile summary, next eligible donation date, and recent history.
    """
    context = {
        'title': 'Donor Dashboard',
        'donor': request.user,
        'next_eligible_date': 'Available now (No prior donations recorded)',
        'total_donations': 0,
        'recent_donations': [],
    }
    return render(request, 'donors/dashboard.html', context)


@login_required
def donation_history(request):
    """
    View donation history including Bag IDs, dates, and locations (SRS 4.2: BBMS-F-007).
    """
    context = {
        'title': 'Donation History',
        'donations': [],
    }
    return render(request, 'donors/history.html', context)


@login_required
def eligibility_check(request):
    """
    Medical eligibility questionnaire skeleton (SRS 4.3: BBMS-F-009, BBMS-F-010).
    """
    context = {
        'title': 'Medical Eligibility Screening',
    }
    return render(request, 'donors/eligibility.html', context)
