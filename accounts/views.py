from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import AuthenticationForm
from django.shortcuts import redirect, render
from .models import User


def login_view(request):
    """
    User login supporting all BBMS roles (Donor, Hospital, Staff, Admin).
    SRS: 4.1 (F-004), 4.13 (F-041), 5.1.2 (SR-001)
    """
    if request.user.is_authenticated:
        return redirect('core:home')

    if request.method == 'POST':
        form = AuthenticationForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            if not user.is_approved:
                messages.error(request, 'Your account is pending administrator approval before activation.')
                return render(request, 'accounts/login.html', {'form': form})
            login(request, user)
            messages.success(request, f'Welcome back, {user.get_full_name() or user.username} ({user.get_role_display()})!')
            return redirect('core:home')
        else:
            messages.error(request, 'Invalid email/username or password.')
    else:
        form = AuthenticationForm(request)

    return render(request, 'accounts/login.html', {'form': form})


def logout_view(request):
    """
    Logs out the authenticated user.
    SRS: 5.1.2 (SR-006)
    """
    logout(request)
    messages.info(request, 'You have been successfully logged out.')
    return redirect('core:home')


def register_donor(request):
    """
    Donor registration endpoint skeleton.
    SRS: 4.1 (BBMS-F-001 to BBMS-F-003)
    """
    if request.user.is_authenticated:
        return redirect('core:home')

    if request.method == 'POST':
        messages.info(request, 'Donor registration processing is ready for module implementation.')
        return redirect('accounts:login')

    return render(request, 'accounts/register_donor.html', {'title': 'Donor Registration'})


def register_hospital(request):
    """
    Hospital registration endpoint skeleton.
    SRS: 4.13 (BBMS-F-040 to BBMS-F-042)
    """
    if request.user.is_authenticated:
        return redirect('core:home')

    if request.method == 'POST':
        messages.info(request, 'Hospital registration submitted and pending admin approval.')
        return redirect('accounts:login')

    return render(request, 'accounts/register_hospital.html', {'title': 'Hospital Registration'})


@login_required
def profile(request):
    """
    View user profile details.
    SRS: 4.2 (BBMS-F-006)
    """
    return render(request, 'accounts/profile.html', {
        'title': 'User Profile',
        'user': request.user
    })
