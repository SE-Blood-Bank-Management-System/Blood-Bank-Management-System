from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin
from core.audit import record_audit_event
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

    def save_model(self, request, obj, form, change):
        if not change:
            super().save_model(request, obj, form, change)
            record_audit_event(
                action='user_created',
                request=request,
                actor=request.user,
                target_type='user',
                target_id=str(obj.pk),
                details={'username': obj.username, 'role': obj.role, 'is_approved': obj.is_approved},
            )
            return

        old_role = form.initial.get('role')
        old_approved = form.initial.get('is_approved')
        old_active = form.initial.get('is_active')

        super().save_model(request, obj, form, change)

        if old_role and old_role != obj.role:
            record_audit_event(
                action='role_changed',
                request=request,
                actor=request.user,
                target_type='user',
                target_id=str(obj.pk),
                details={'username': obj.username, 'old_role': old_role, 'new_role': obj.role},
            )
        if old_approved is not None and old_approved != obj.is_approved:
            record_audit_event(
                action='hospital_approved' if obj.is_approved else 'hospital_approval_revoked',
                request=request,
                actor=request.user,
                target_type='user',
                target_id=str(obj.pk),
                details={'username': obj.username, 'is_approved': obj.is_approved},
            )
        if old_active is not None and old_active != obj.is_active:
            record_audit_event(
                action='user_reactivated' if obj.is_active else 'user_deactivated',
                request=request,
                actor=request.user,
                target_type='user',
                target_id=str(obj.pk),
                details={'username': obj.username, 'is_active': obj.is_active},
            )

    def delete_model(self, request, obj):
        obj._audit_deleted_recorded = True
        record_audit_event(
            action='user_deleted',
            request=request,
            actor=request.user,
            target_type='user',
            target_id=str(obj.pk),
            details={'username': obj.username, 'role': obj.role},
        )
        super().delete_model(request, obj)

    @admin.action(description='Approve selected accounts (SRS BBMS-F-062)')
    def approve_accounts(self, request, queryset):
        count = 0
        for user in queryset:
            was_approved = user.is_approved
            user.is_approved = True
            user.save(update_fields=['is_approved'])
            if not was_approved:
                record_audit_event(
                    action='hospital_approved',
                    request=request,
                    actor=request.user,
                    target_type='user',
                    target_id=str(user.pk),
                    details={'username': user.username, 'role': user.role, 'is_approved': True},
                )
            count += 1
        self.message_user(
            request,
            f'{count} account(s) successfully approved and activated.',
            messages.SUCCESS
        )

    @admin.action(description='Deactivate selected user accounts (SRS BBMS-F-060, BBMS-F-063)')
    def deactivate_accounts(self, request, queryset):
        count = 0
        for user in queryset:
            was_active = user.is_active
            user.is_active = False
            user.save(update_fields=['is_active'])
            if was_active:
                record_audit_event(
                    action='user_deactivated',
                    request=request,
                    actor=request.user,
                    target_type='user',
                    target_id=str(user.pk),
                    details={'username': user.username, 'role': user.role, 'is_active': False},
                )
            count += 1
        self.message_user(
            request,
            f'{count} account(s) deactivated. Authentication will be denied.',
            messages.WARNING
        )

    @admin.action(description='Reactivate selected user accounts (SRS BBMS-F-060)')
    def reactivate_accounts(self, request, queryset):
        count = 0
        for user in queryset:
            was_active = user.is_active
            user.is_active = True
            user.save(update_fields=['is_active'])
            if not was_active:
                record_audit_event(
                    action='user_reactivated',
                    request=request,
                    actor=request.user,
                    target_type='user',
                    target_id=str(user.pk),
                    details={'username': user.username, 'role': user.role, 'is_active': True},
                )
            count += 1
        self.message_user(
            request,
            f'{count} account(s) successfully reactivated.',
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
        count = 0
        for state in queryset:
            state.failed_attempts = 0
            state.lockout_until = None
            state.save(update_fields=['failed_attempts', 'lockout_until'])
            record_audit_event(
                action='lockout_cleared',
                request=request,
                actor=request.user,
                target_type='account',
                target_id=state.identifier,
                details={'identifier': state.identifier},
            )
            count += 1
        self.message_user(request, f"Lockout cleared for {count} account(s).", messages.SUCCESS)


@admin.register(LoginRateLimitRecord)
class LoginRateLimitRecordAdmin(admin.ModelAdmin):
    list_display = ('ip_address', 'timestamp')
    search_fields = ('ip_address',)
    readonly_fields = ('ip_address', 'timestamp')
