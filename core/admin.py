from django.contrib import admin
from .models import SecurityAuditEvent


@admin.register(SecurityAuditEvent)
class SecurityAuditEventAdmin(admin.ModelAdmin):
    list_display = ('timestamp', 'action', 'severity', 'actor_label', 'ip_address', 'target_type', 'target_id')
    list_filter = ('severity', 'action')
    search_fields = ('actor_label', 'ip_address', 'action', 'target_id')
    readonly_fields = (
        'timestamp', 'action', 'severity', 'actor', 'actor_label',
        'ip_address', 'user_agent', 'target_type', 'target_id', 'details',
    )
    ordering = ('-timestamp',)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
