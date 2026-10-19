from django.shortcuts import render
from django.contrib.auth.decorators import login_required


@login_required
def inventory_dashboard(request):
    """
    Inventory management dashboard for staff and administrators.
    Displays units by blood group, component type, and FEFO expiry status.
    SRS: 4.11 (BBMS-F-033, BBMS-F-034), 4.12 (BBMS-F-037 to BBMS-F-039)
    """
    blood_groups = ['A+', 'A-', 'B+', 'B-', 'AB+', 'AB-', 'O+', 'O-']
    components = ['Whole Blood', 'Red Blood Cells', 'Platelets', 'Fresh Frozen Plasma']

    context = {
        'title': 'Blood Inventory Dashboard',
        'blood_groups': blood_groups,
        'components': components,
        'total_units_available': 0,
        'quarantined_units': 0,
        'expiring_soon_count': 0,
    }
    return render(request, 'inventory/dashboard.html', context)


@login_required
def quarantine_list(request):
    """
    List units pending serology testing or under quarantine (SRS 4.8, 4.9: BBMS-F-026 to BBMS-F-030).
    """
    context = {
        'title': 'Quarantine & Serology Testing',
        'quarantined_units': [],
    }
    return render(request, 'inventory/quarantine.html', context)
