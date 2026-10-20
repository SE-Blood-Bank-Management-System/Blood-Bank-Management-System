from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import AuthenticationForm
from django.db import IntegrityError
from django.shortcuts import redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from .forms import DonorRegistrationForm, HospitalRegistrationForm, UserProfileUpdateForm
from .models import User


def login_view(request):
    """
    User login supporting all BBMS roles (Donor, Hospital, Staff, Admin)
    with authentication by either username or email and role-directed redirection.
    SRS: 4.1 (BBMS-F-004), 4.13 (BBMS-F-041), 4.20 (BBMS-F-063), 5.1.2 (BBMS-SR-001, BBMS-SR-007).
    """
    if request.user.is_authenticated:
        return redirect('core:home')

    if request.method == 'POST':
        form = AuthenticationForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()

            # Account status checks
            if not user.is_active:
                messages.error(
                    request,
                    'Your account has been deactivated. Please contact an administrator (SRS BBMS-F-063).'
                )
                return render(request, 'accounts/login.html', {'form': form})

            if not user.is_approved:
                messages.error(
                    request,
                    'Your account is pending administrator approval before activation (SRS BBMS-F-040, BBMS-F-042).'
                )
                return render(request, 'accounts/login.html', {'form': form})

            login(request, user)
            messages.success(
                request,
                f'Welcome back, {user.get_full_name() or user.username} ({user.get_role_display()})!'
            )

            # Redirect handling: safe next parameter, else role dashboard
            next_url = request.POST.get('next') or request.GET.get('next')
            if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
                return redirect(next_url)

            if user.is_donor:
                return redirect('donors:dashboard')
            elif user.is_staff_member:
                return redirect('inventory:dashboard')
            elif user.is_hospital:
                return redirect('core:home')
            else:
                return redirect('core:home')
        else:
            messages.error(request, 'Invalid email/username or password.')
    else:
        form = AuthenticationForm(request)

    return render(request, 'accounts/login.html', {'form': form})


def logout_view(request):
    """
    Logs out the authenticated user and invalidates session.
    SRS: 5.1.2 (BBMS-SR-006).
    """
    logout(request)
    messages.info(request, 'You have been successfully logged out.')
    return redirect('core:home')


def register_donor(request):
    """
    Donor registration endpoint enforcing 18+ age validation, unique email,
    and automatic account activation.
    SRS: 4.1 (BBMS-F-001, BBMS-F-002, BBMS-F-003, BBMS-F-004), 5.1.2 (BBMS-SR-002).
    """
    if request.user.is_authenticated:
        return redirect('core:home')

    if request.method == 'POST':
        form = DonorRegistrationForm(request.POST)
        if form.is_valid():
            try:
                user = form.save()
            except IntegrityError:
                # A competing registration may claim this email after validation.
                if not User.objects.filter(email__iexact=form.cleaned_data['email']).exists():
                    raise
                form.add_error('email', 'An account with this email address already exists.')
            else:
                login(request, user, backend='accounts.backends.EmailOrUsernameModelBackend')
                messages.success(
                    request,
                    f'Welcome to BBMS, {user.get_full_name() or user.username}! Your donor account is active.'
                )
                return redirect('donors:dashboard')
    else:
        form = DonorRegistrationForm()

    return render(request, 'accounts/register_donor.html', {
        'title': 'Donor Registration',
        'form': form
    })


def register_hospital(request):
    """
    Hospital registration endpoint collecting institution and contact details.
    Hospital accounts are created in unapproved status pending admin review.
    SRS: 4.13 (BBMS-F-040, BBMS-F-042).
    """
    if request.user.is_authenticated:
        return redirect('core:home')

    if request.method == 'POST':
        form = HospitalRegistrationForm(request.POST)
        if form.is_valid():
            user = form.save()
            messages.info(
                request,
                f'Registration for {user.hospital_name or user.username} submitted successfully! '
                'Your account is pending administrator approval before activation (SRS BBMS-F-040, BBMS-F-042).'
            )
            return redirect('accounts:login')
        else:
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, error)
    else:
        form = HospitalRegistrationForm()

    return render(request, 'accounts/register_hospital.html', {
        'title': 'Hospital Registration',
        'form': form
    })


@login_required
def profile(request):
    """
    View and update user profile details (contact number, address, blood group).
    SRS: 4.2 (BBMS-F-006).
    """
    if request.method == 'POST':
        form = UserProfileUpdateForm(request.POST, instance=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, 'Profile details updated successfully (SRS BBMS-F-006).')
            return redirect('accounts:profile')
        else:
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, error)
    else:
        form = UserProfileUpdateForm(instance=request.user)

    return render(request, 'accounts/profile.html', {
        'title': 'User Profile',
        'user': request.user,
        'form': form
    })
