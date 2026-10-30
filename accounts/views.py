import logging
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.tokens import default_token_generator
from django.core.mail import send_mail
from django.db import IntegrityError
from django.shortcuts import redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.encoding import force_bytes, force_str
from django.utils.http import url_has_allowed_host_and_scheme, urlsafe_base64_decode, urlsafe_base64_encode
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods, require_POST
from core.audit import record_security_event
from donors.services import donation_summary
from .forms import (
    DonorRegistrationForm,
    HospitalRegistrationForm,
    LoginForm,
    PasswordResetRequestForm,
    SetNewPasswordForm,
    UserProfileUpdateForm,
)
from .models import LoginSecurityState, User

logger = logging.getLogger('bbms.security')


@never_cache
@require_http_methods(['GET', 'POST'])
def login_view(request):
    """
    User login supporting all BBMS roles (Donor, Hospital, Staff, Admin)
    with authentication by either username or email and role-directed redirection.
    SRS: 4.1 (BBMS-F-004), 4.13 (BBMS-F-041), 4.20 (BBMS-F-063), 5.1.2 (BBMS-SR-001, BBMS-SR-006).
    """
    if request.user.is_authenticated:
        return redirect('core:home')

    next_url = request.POST.get('next') or request.GET.get('next', '')
    if not url_has_allowed_host_and_scheme(
        next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        next_url = ''

    if request.method == 'POST':
        form = LoginForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()

            login(request, user)
            messages.success(
                request,
                f'Welcome back, {user.get_full_name() or user.username} ({user.get_role_display()})!'
            )

            # Redirect handling: safe next parameter, else role dashboard
            if next_url:
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
        form = LoginForm(request)

    return render(request, 'accounts/login.html', {'form': form, 'next': next_url})


@never_cache
@require_POST
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
                record_security_event(
                    action='donor_registered',
                    request=request,
                    actor=user,
                    actor_label=user.username,
                    target_type='user',
                    target_id=str(user.pk),
                    details={'username': user.username, 'role': user.role, 'email': user.email},
                )
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
            record_security_event(
                action='hospital_registered',
                request=request,
                actor=user,
                actor_label=user.username,
                target_type='user',
                target_id=str(user.pk),
                details={
                    'username': user.username,
                    'hospital_name': user.hospital_name,
                    'license_number': user.license_number,
                    'is_approved': user.is_approved,
                },
            )
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
@never_cache
@require_http_methods(['GET', 'POST'])
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
        form = UserProfileUpdateForm(instance=request.user)

    return render(request, 'accounts/profile.html', {
        **(donation_summary(request.user) if request.user.is_donor else {}),
        'title': 'User Profile',
        'user': request.user,
        'form': form
    })


@never_cache
@require_http_methods(['GET', 'POST'])
def password_reset_request(request):
    """
    Initiates a secure password reset request (SRS BBMS-F-005).
    Delivers a single-use time-limited reset token via environment-configured SMTP.
    Always displays a generic response to prevent user enumeration attacks.
    """
    if request.user.is_authenticated:
        return redirect('core:home')

    if request.method == 'POST':
        form = PasswordResetRequestForm(request.POST)
        if form.is_valid():
            email = form.cleaned_data['email']
            user = User.objects.filter(email__iexact=email, is_active=True).first()
            if user:
                token = default_token_generator.make_token(user)
                uidb64 = urlsafe_base64_encode(force_bytes(user.pk))
                reset_url = request.build_absolute_uri(
                    reverse('accounts:password_reset_confirm', kwargs={'uidb64': uidb64, 'token': token})
                )
                context = {
                    'user': user,
                    'reset_url': reset_url,
                    'timeout_minutes': settings.PASSWORD_RESET_TIMEOUT // 60,
                }
                text_message = render_to_string('accounts/email/password_reset_email.txt', context)
                html_message = render_to_string('accounts/email/password_reset_email.html', context)
                try:
                    send_mail(
                        subject='BBMS - Password Reset Instructions',
                        message=text_message,
                        from_email=settings.DEFAULT_FROM_EMAIL,
                        recipient_list=[user.email],
                        html_message=html_message,
                        fail_silently=False,
                    )
                except Exception as exc:
                    logger.error("Failed to deliver password reset email: %s", exc)

                record_security_event(
                    action='password_reset_request',
                    request=request,
                    actor=user,
                    actor_label=user.username,
                    target_type='account',
                    target_id=str(user.pk),
                    details={'email': user.email},
                    severity='INFO',
                )
            else:
                record_security_event(
                    action='password_reset_request_unknown',
                    request=request,
                    actor_label=email,
                    target_type='account',
                    details={'requested_email': email},
                    severity='INFO',
                )

            # Generic redirection regardless of whether user exists
            return redirect('accounts:password_reset_done')
    else:
        form = PasswordResetRequestForm()

    return render(request, 'accounts/password_reset_request.html', {'form': form})


def password_reset_done(request):
    """
    Generic confirmation screen after requesting a password reset (SRS BBMS-F-005).
    """
    return render(request, 'accounts/password_reset_done.html')


@never_cache
@require_http_methods(['GET', 'POST'])
def password_reset_confirm(request, uidb64, token):
    """
    Validates single-use, time-limited reset token and allows setting a new password (SRS BBMS-F-005).
    Clears any active account lockout on successful completion.
    """
    try:
        uid = force_str(urlsafe_base64_decode(uidb64))
        user = User.objects.get(pk=uid, is_active=True)
    except (TypeError, ValueError, OverflowError, User.DoesNotExist):
        user = None

    validlink = (user is not None) and default_token_generator.check_token(user, token)

    if not validlink:
        record_security_event(
            action='password_reset_invalid_token',
            request=request,
            actor=user,
            actor_label=user.username if user else 'unknown',
            target_type='account',
            target_id=str(user.pk) if user else '',
            severity='WARNING',
        )
        return render(request, 'accounts/password_reset_confirm.html', {'validlink': False})

    if request.method == 'POST':
        form = SetNewPasswordForm(user, request.POST)
        if form.is_valid():
            form.save()
            # Clear lockout state so user can immediately sign in
            LoginSecurityState.objects.filter(user=user).update(
                failed_attempts=0,
                lockout_until=None
            )
            record_security_event(
                action='password_reset_success',
                request=request,
                actor=user,
                actor_label=user.username,
                target_type='account',
                target_id=str(user.pk),
                severity='INFO',
            )
            messages.success(request, 'Your password has been reset successfully. Please sign in.')
            return redirect('accounts:password_reset_complete')
    else:
        form = SetNewPasswordForm(user)

    return render(request, 'accounts/password_reset_confirm.html', {'form': form, 'validlink': True})


def password_reset_complete(request):
    """
    Success confirmation screen after resetting password (SRS BBMS-F-005).
    """
    return render(request, 'accounts/password_reset_complete.html')
