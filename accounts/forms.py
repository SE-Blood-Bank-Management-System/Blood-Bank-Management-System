import re
from uuid import uuid4

from django import forms
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from .models import User


class LoginForm(AuthenticationForm):
    username = forms.CharField(label='Email or username', max_length=254)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Email is longer than AbstractUser.username, but uses the same login field.
        self.fields['username'].max_length = 254
        self.fields['username'].widget.attrs['maxlength'] = 254

    def confirm_login_allowed(self, user):
        super().confirm_login_allowed(user)
        if not user.is_approved:
            raise forms.ValidationError('Your account is pending administrator approval.', code='unapproved')


class DonorRegistrationForm(forms.ModelForm):
    """
    Donor registration form enforcing:
    - Required fields: name, email, dob, phone, gender, password (BBMS-F-001)
    - Minimum age validation of 18 years from date of birth (BBMS-F-002)
    - Unique email per donor account (BBMS-F-003)
    - Strong password hashing via PBKDF2/bcrypt (BBMS-SR-002)
    """
    dob = forms.DateField(
        label='Date of birth',
        help_text='You must be at least 18 years old to register.',
        required=True,
        widget=forms.DateInput(attrs={'type': 'date', 'class': 'form-control'})
    )
    password = forms.CharField(
        required=True,
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'Choose a secure password'}),
    )
    first_name = forms.CharField(
        max_length=150,
        required=True,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'First Name'})
    )
    last_name = forms.CharField(
        max_length=150,
        required=True,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Last Name'})
    )
    email = forms.EmailField(
        required=True,
        widget=forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'john.doe@example.com'})
    )
    phone = forms.CharField(
        label='Contact number',
        help_text='Enter 7 to 15 digits; spaces, parentheses, hyphens and a leading + are allowed.',
        max_length=20,
        required=True,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': '+91 9876543210'})
    )
    gender = forms.ChoiceField(
        choices=[('', 'Select Gender')] + list(User.Gender.choices),
        required=True,
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    blood_group = forms.ChoiceField(
        label='Self-reported blood group',
        choices=[('', 'Unknown / Not sure')] + list(User.BloodGroup.choices),
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'})
    )

    class Meta:
        model = User
        fields = ('first_name', 'last_name', 'email', 'dob', 'phone', 'gender', 'blood_group', 'password')

    def clean_dob(self):
        dob = self.cleaned_data.get('dob')
        if not dob:
            raise forms.ValidationError("Date of birth is required.")
        today = timezone.now().date()
        age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
        if age < 18:
            raise forms.ValidationError("Donors must be at least 18 years old to register (SRS BBMS-F-002).")
        return dob

    def clean_email(self):
        email = self.cleaned_data.get('email')
        if not email:
            raise forms.ValidationError("Email address is required.")
        clean_email = email.strip().lower()
        if User.objects.filter(email__iexact=clean_email).exists():
            raise forms.ValidationError("An account with this email address already exists (SRS BBMS-F-003).")
        if User.objects.filter(username__iexact=clean_email).exists():
            raise forms.ValidationError('This email is already used as an account username. Please contact support.')
        return clean_email

    def clean_phone(self):
        phone = self.cleaned_data['phone']
        digits = re.sub(r'\D', '', phone)
        if not re.fullmatch(r'\+?[0-9 ()-]+', phone) or not 7 <= len(digits) <= 15:
            raise forms.ValidationError('Enter a valid contact number containing 7 to 15 digits.')
        return phone

    def _post_clean(self):
        super()._post_clean()
        # ModelForm has now populated the applicant's name and email on the user.
        password = self.cleaned_data.get('password')
        if password:
            try:
                validate_password(password, self.instance)
            except ValidationError as errors:
                self.add_error('password', errors)

    @transaction.atomic
    def save(self, commit=True):
        user = super().save(commit=False)
        user.role = User.Role.DONOR
        user.is_approved = True
        user.date_of_birth = self.cleaned_data.get('dob')
        user.email = self.cleaned_data.get('email')
        # Use email as username if not specified
        user.username = self.cleaned_data.get('email')
        # Email accepts 254 characters; AbstractUser.username accepts only 150.
        if len(user.username) > 150:
            user.username = f'donor_{uuid4().hex}'
        user.set_password(self.cleaned_data.get('password'))
        if commit:
            user.save()
        return user


class HospitalRegistrationForm(forms.ModelForm):
    """
    Hospital registration form collecting facility and contact details.
    Hospital accounts are created in unapproved status pending admin review.
    SRS: 4.13 (BBMS-F-040, BBMS-F-042).
    """
    password = forms.CharField(
        required=True,
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'Choose password'}),
        validators=[validate_password]
    )
    hospital_name = forms.CharField(
        max_length=255,
        required=True,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'City General Hospital'})
    )
    license_number = forms.CharField(
        max_length=100,
        required=True,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'REG-HOSP-2026-981'})
    )
    email = forms.EmailField(
        required=True,
        widget=forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'bloodbank@cityhospital.org'})
    )
    contact_person = forms.CharField(
        max_length=150,
        required=True,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Dr. S. Sharma'})
    )
    phone = forms.CharField(
        max_length=20,
        required=True,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': '+91 80 2345 6789'})
    )
    address = forms.CharField(
        required=True,
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': 'Facility address'})
    )

    class Meta:
        model = User
        fields = ('hospital_name', 'license_number', 'email', 'contact_person', 'phone', 'address', 'password')

    def clean_email(self):
        email = self.cleaned_data.get('email')
        if not email:
            raise forms.ValidationError("Email address is required.")
        clean_email = email.strip().lower()
        if User.objects.filter(email__iexact=clean_email).exists():
            raise forms.ValidationError("An account with this email address already exists.")
        return clean_email

    def save(self, commit=True):
        user = super().save(commit=False)
        user.role = User.Role.HOSPITAL
        user.is_approved = False  # Pending administrator approval (SRS BBMS-F-040, BBMS-F-042)
        user.email = self.cleaned_data.get('email')
        user.username = self.cleaned_data.get('email')
        user.set_password(self.cleaned_data.get('password'))
        if commit:
            user.save()
        return user


class UserProfileUpdateForm(forms.ModelForm):
    """
    Form allowing users (especially donors) to view and update contact and demographic details.
    SRS: 4.2 (BBMS-F-006).
    """
    phone = forms.CharField(
        max_length=20,
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control'})
    )
    address = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 2})
    )
    blood_group = forms.ChoiceField(
        choices=[('', 'Unknown / Not sure')] + list(User.BloodGroup.choices),
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'})
    )

    class Meta:
        model = User
        fields = ('phone', 'address', 'blood_group')
