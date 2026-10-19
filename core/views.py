from django.shortcuts import render


def home(request):
    """
    Landing / Home page for BBMS.
    Provides role-oriented call-to-actions and overview.
    SRS: 2.1, 3.1
    """
    context = {
        'title': 'Blood Bank Management System',
        'stats': {
            'blood_groups_count': 8,
            'standard_components': ['Whole Blood', 'Red Blood Cells', 'Platelets', 'Fresh Frozen Plasma'],
        }
    }
    return render(request, 'core/home.html', context)


def public_availability(request):
    """
    Public-facing blood availability lookup (SRS BBMS-F-067, BBMS-F-068).
    Accessible without authentication; excludes donor/hospital PII.
    """
    # Sample structured availability data as placeholder until database integration
    sample_inventory = [
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
        'inventory_summary': sample_inventory,
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
