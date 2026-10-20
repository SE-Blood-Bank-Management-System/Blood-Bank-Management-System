from django.contrib.auth.models import AbstractUser, UserManager
from django.db import models
from django.utils import timezone


class CustomUserManager(UserManager):
    """
    Custom user manager supporting unique email handling and default role assignments.
    SRS: BBMS-F-001, BBMS-F-003, BBMS-SR-001.
    """
    def create_user(self, username, email=None, password=None, **extra_fields):
        if email:
            email = self.normalize_email(email).strip().lower()
        else:
            email = None
        extra_fields.setdefault('is_staff', False)
        extra_fields.setdefault('is_superuser', False)
        return super().create_user(username, email, password, **extra_fields)

    def create_superuser(self, username, email=None, password=None, **extra_fields):
        extra_fields.setdefault('role', User.Role.ADMIN)
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('is_approved', True)

        if extra_fields.get('role') != User.Role.ADMIN:
            raise ValueError('Superuser must have role=ADMIN.')
        if extra_fields.get('is_staff') is not True:
            raise ValueError('Superuser must have is_staff=True.')
        if extra_fields.get('is_superuser') is not True:
            raise ValueError('Superuser must have is_superuser=True.')

        return super().create_superuser(username, email, password, **extra_fields)


class User(AbstractUser):
    """
    Custom user model supporting Role-Based Access Control (RBAC)
    for all BBMS roles: Donor, Hospital User, Blood Bank Staff, and Administrator.
    SRS: Section 2.3, 4.1 (F-001 to F-004), 4.7 (F-022), 4.13 (F-040 to F-042),
         4.20 (F-060 to F-063), 5.1.2 (SR-001, SR-002, SR-003).
    """
    class Role(models.TextChoices):
        DONOR = 'DONOR', 'Donor'
        HOSPITAL = 'HOSPITAL', 'Hospital User'
        STAFF = 'STAFF', 'Blood Bank Staff'
        ADMIN = 'ADMIN', 'Administrator'

    class Gender(models.TextChoices):
        MALE = 'Male', 'Male'
        FEMALE = 'Female', 'Female'
        OTHER = 'Other', 'Other'

    class BloodGroup(models.TextChoices):
        A_POS = 'A+', 'A+'
        A_NEG = 'A-', 'A-'
        B_POS = 'B+', 'B+'
        B_NEG = 'B-', 'B-'
        AB_POS = 'AB+', 'AB+'
        AB_NEG = 'AB-', 'AB-'
        O_POS = 'O+', 'O+'
        O_NEG = 'O-', 'O-'

    # Unique email address per account (SRS BBMS-F-003, BBMS-SR-001)
    email = models.EmailField(
        unique=True,
        null=True,
        blank=True,
        help_text='Unique email address for authentication and notifications (SRS BBMS-F-003)'
    )

    role = models.CharField(
        max_length=20,
        choices=Role.choices,
        default=Role.DONOR,
        help_text='Assigned role for role-based access control and navigation'
    )
    phone = models.CharField(
        max_length=20,
        blank=True,
        help_text='Contact phone number'
    )
    date_of_birth = models.DateField(
        null=True,
        blank=True,
        help_text='Date of birth for donor eligibility calculation (SRS BBMS-F-001, BBMS-F-002)'
    )
    gender = models.CharField(
        max_length=10,
        choices=Gender.choices,
        blank=True,
        help_text='Gender of user/donor (SRS BBMS-F-001)'
    )
    blood_group = models.CharField(
        max_length=5,
        choices=BloodGroup.choices,
        blank=True,
        help_text='Self-reported or confirmed ABO/Rh blood group (SRS BBMS-F-006, BBMS-F-022)'
    )
    address = models.TextField(
        blank=True,
        help_text='Residential or institutional address (SRS BBMS-F-006, BBMS-F-040)'
    )

    # Hospital-specific registration fields (SRS BBMS-F-040)
    hospital_name = models.CharField(
        max_length=255,
        blank=True,
        help_text='Registered hospital name'
    )
    license_number = models.CharField(
        max_length=100,
        blank=True,
        help_text='Hospital registration or license number'
    )
    contact_person = models.CharField(
        max_length=150,
        blank=True,
        help_text='Primary contact person for hospital'
    )

    is_approved = models.BooleanField(
        default=True,
        help_text='Approval flag (e.g. hospital accounts require admin approval before activation)'
    )

    objects = CustomUserManager()

    @property
    def is_donor(self):
        return self.role == self.Role.DONOR

    @property
    def is_hospital(self):
        return self.role == self.Role.HOSPITAL

    @property
    def is_staff_member(self):
        return self.role == self.Role.STAFF or self.is_staff or self.is_superuser

    @property
    def is_administrator(self):
        return self.role == self.Role.ADMIN or self.is_superuser

    @property
    def age(self):
        """
        Calculates user's age in full years based on server date (authoritative clock).
        SRS: 2.6, 4.1 (BBMS-F-002).
        """
        if not self.date_of_birth:
            return None
        today = timezone.now().date()
        return today.year - self.date_of_birth.year - (
            (today.month, today.day) < (self.date_of_birth.month, self.date_of_birth.day)
        )

    @property
    def is_donor_eligible_age(self):
        """
        Returns True if the donor is at least 18 years old.
        SRS: BBMS-F-002.
        """
        user_age = self.age
        return user_age is not None and user_age >= 18

    def has_role(self, *roles):
        """
        Check if user has any of the given roles.
        Superusers satisfy ADMIN and STAFF checks.
        """
        if self.is_superuser and (self.Role.ADMIN in roles or self.Role.STAFF in roles):
            return True
        return self.role in roles

    def has_perm_code(self, perm_code):
        """
        Check if the user has a specific BBMS domain permission code.
        SRS BBMS-F-061, BBMS-SR-003.
        """
        from .rbac import ROLE_PERMISSIONS
        if not self.is_authenticated:
            return False
        if self.is_superuser or self.role == self.Role.ADMIN:
            return True
        allowed_perms = ROLE_PERMISSIONS.get(self.role, set())
        return perm_code in allowed_perms

    def clean(self):
        super().clean()
        if self.email:
            self.email = self.email.strip().lower()
        else:
            self.email = None

    def save(self, *args, **kwargs):
        if not self.email:
            self.email = None
        else:
            self.email = self.email.strip().lower()
        if self.is_superuser and self.role != self.Role.ADMIN:
            self.role = self.Role.ADMIN
            self.is_staff = True
            self.is_approved = True
        super().save(*args, **kwargs)

    def __str__(self):
        identifier = self.get_full_name() or self.username
        return f"{identifier} ({self.get_role_display()})"
