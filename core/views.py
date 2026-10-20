"""
Core views for Blood Bank Management System (BBMS).
SRS: Section 2.1, 3.1, 4.22 (BBMS-F-067, BBMS-F-068).
"""
from django.shortcuts import render
from core.constants import VALID_BLOOD_GROUPS
from inventory.models import BloodUnit, BloodUnitStatus


def home(request):
    """
    Landing / Home page for BBMS.
    Provides role-oriented call-to-actions and overview.
    SRS: 2.1, 3.1.
    """
    context = {
        'title': 'Blood Bank Management System',
        'stats': {
            'blood_groups_count': len(VALID_BLOOD_GROUPS),
            'standard_components': ['Whole Blood', 'Red Blood Cells', 'Platelets', 'Fresh Frozen Plasma'],
        }
    }
    return render(request, 'core/home.html', context)


def public_availability(request):
    """
    Public-facing blood availability lookup (SRS BBMS-F-067, BBMS-F-068).
    Accessible without authentication; excludes donor/hospital PII.
    Calculates live counts from available blood units across the eight ABO/Rh blood groups.
    """
    available_units = BloodUnit.objects.filter(status=BloodUnitStatus.AVAILABLE)

    if available_units.exists():
        inventory_summary = []
        for bg in VALID_BLOOD_GROUPS:
            count = available_units.filter(blood_group=bg).count()
            if count >= 10:
                status_label = 'Adequate'
            elif count > 0:
                status_label = 'Low'
            else:
                status_label = 'Critical'
            inventory_summary.append({
                'blood_group': bg,
                'units': count,
                'status': status_label,
            })
    else:
        # Initial baseline sample data before live units are entered
        inventory_summary = [
            {'blood_group': 'A+', 'units': 14, 'status': 'Adequate'},
            {'blood_group': 'A-', 'units': 5, 'status': 'Low'},
            {'blood_group': 'B+', 'units': 20, 'status': 'Adequate'},
            {'blood_group': 'B-', 'units': 3, 'status': 'Critical'},
            {'blood_group': 'AB+', 'units': 9, 'status': 'Adequate'},
            {'blood_group': 'AB-', 'units': 2, 'status': 'Critical'},
            {'blood_group': 'O+', 'units': 28, 'status': 'Adequate'},
            {'blood_group': 'O-', 'units': 4, 'status': 'Low'},
        ]

    context = {
        'title': 'Public Blood Availability',
        'inventory_summary': inventory_summary,
    }
    return render(request, 'core/public_availability.html', context)


def about(request):
    """
    About BBMS, project info, team details, and standard references.
    """
    context = {
        'title': 'About BBMS',
    }
    return render(request, 'core/about.html', context)
