from django.contrib import admin
from .models import SecurityAuditEvent


@admin.register(SecurityAuditEvent)
class SecurityAuditEventAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'timestamp', 'action', 'severity', 'actor_label',
        'ip_address', 'target_type', 'target_id', 'record_hash_short',
    )
    list_filter = ('severity', 'action', 'target_type')
    search_fields = ('actor_label', 'ip_address', 'action', 'target_id')
    readonly_fields = (
        'timestamp', 'action', 'severity', 'actor', 'actor_label',
        'ip_address', 'user_agent', 'target_type', 'target_id', 'details',
        'prev_hash', 'record_hash',
    )
    ordering = ('-timestamp', '-id')
    actions = None  # Explicitly disable bulk delete and any mutation actions

    @admin.display(description='Hash')
    def record_hash_short(self, obj):
        if obj.record_hash:
            return f"{obj.record_hash[:12]}..."
        return ""

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
