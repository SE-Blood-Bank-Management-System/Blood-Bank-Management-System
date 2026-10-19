from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """
    Custom user model supporting Role-Based Access Control (RBAC)
    for BBMS roles: Donor, Hospital User, Blood Bank Staff, and Administrator.
    """
    class Role(models.TextChoices):
        DONOR = 'DONOR', 'Donor'
        HOSPITAL = 'HOSPITAL', 'Hospital User'
        STAFF = 'STAFF', 'Blood Bank Staff'
        ADMIN = 'ADMIN', 'Administrator'

    role = models.CharField(
        max_length=20,
        choices=Role.choices,
        default=Role.DONOR,
        help_text='Assigned role for role-based access control and navigation'
    )
    phone = models.CharField(max_length=20, blank=True, help_text='Contact phone number')
    is_approved = models.BooleanField(
        default=True,
        help_text='Approval flag (e.g. hospital accounts require admin approval before activation)'
    )

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

    def save(self, *args, **kwargs):
        if self.is_superuser and self.role != self.Role.ADMIN:
            self.role = self.Role.ADMIN
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.username} ({self.get_role_display()})"
