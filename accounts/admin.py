from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin
from .models import LoginRateLimitRecord, LoginSecurityState, User


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    """
    Administrator panel for BBMS user and role management.
    SRS: 4.20 (BBMS-F-060, BBMS-F-061, BBMS-F-062, BBMS-F-063).
    """
    fieldsets = (
        (None, {'fields': ('username', 'password')}),
        ('Personal Info', {
            'fields': (
                'first_name', 'last_name', 'email', 'phone',
                'date_of_birth', 'gender', 'blood_group', 'address'
            )
        }),
        ('Hospital Facility Info', {'fields': ('hospital_name', 'license_number', 'contact_person')}),
        ('BBMS Role & Approvals', {'fields': ('role', 'is_approved', 'is_active', 'is_staff', 'is_superuser')}),
        ('Permissions & Groups', {'fields': ('groups', 'user_permissions')}),
        ('Important Dates', {'fields': ('last_login', 'date_joined')}),
    )

    add_fieldsets = UserAdmin.add_fieldsets + (
        ('BBMS Role & Profile', {
            'fields': (
                'role', 'email', 'phone', 'date_of_birth', 'gender',
                'blood_group', 'address', 'hospital_name', 'license_number',
                'contact_person', 'is_approved'
            )
        }),
    )

    list_display = (
        'username', 'email', 'get_full_name', 'role', 'phone',
        'is_approved', 'is_active', 'is_staff'
    )
    list_filter = ('role', 'is_approved', 'is_active', 'blood_group', 'gender')
    search_fields = ('username', 'email', 'first_name', 'last_name', 'phone', 'hospital_name', 'license_number')
    ordering = ('username',)
    actions = ['approve_accounts', 'deactivate_accounts', 'reactivate_accounts']

    @admin.action(description='Approve selected accounts (SRS BBMS-F-062)')
    def approve_accounts(self, request, queryset):
        updated = queryset.update(is_approved=True)
        self.message_user(
            request,
            f'{updated} account(s) successfully approved and activated.',
            messages.SUCCESS
        )

    @admin.action(description='Deactivate selected user accounts (SRS BBMS-F-060, BBMS-F-063)')
    def deactivate_accounts(self, request, queryset):
        updated = queryset.update(is_active=False)
        self.message_user(
            request,
            f'{updated} account(s) deactivated. Authentication will be denied.',
            messages.WARNING
        )

    @admin.action(description='Reactivate selected user accounts (SRS BBMS-F-060)')
    def reactivate_accounts(self, request, queryset):
        updated = queryset.update(is_active=True)
        self.message_user(
            request,
            f'{updated} account(s) successfully reactivated.',
            messages.SUCCESS
        )


@admin.register(LoginSecurityState)
class LoginSecurityStateAdmin(admin.ModelAdmin):
    list_display = ('identifier', 'failed_attempts', 'lockout_until', 'last_failed_at', 'last_success_at')
    search_fields = ('identifier',)
    readonly_fields = ('created_at', 'updated_at', 'last_failed_at', 'last_success_at')
    actions = ['clear_lockout']

    @admin.action(description='Clear lockout and reset failed attempts for selected accounts')
    def clear_lockout(self, request, queryset):
        count = queryset.update(failed_attempts=0, lockout_until=None)
        self.message_user(request, f"Lockout cleared for {count} account(s).", messages.SUCCESS)


@admin.register(LoginRateLimitRecord)
class LoginRateLimitRecordAdmin(admin.ModelAdmin):
    list_display = ('ip_address', 'timestamp')
    search_fields = ('ip_address',)
    readonly_fields = ('ip_address', 'timestamp')

