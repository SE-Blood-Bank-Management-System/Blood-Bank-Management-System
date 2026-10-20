from django.contrib import admin
from .models import MedicalEligibilityResponse


@admin.register(MedicalEligibilityResponse)
class MedicalEligibilityResponseAdmin(admin.ModelAdmin):
    list_display = ('donor', 'status', 'created_at', 'is_eligible')
    list_filter = ('status', 'created_at')
    search_fields = ('donor__username', 'donor__email', 'ineligibility_reason')
    readonly_fields = ('donor', 'status', 'responses', 'ineligibility_reason', 'created_at', 'updated_at')

    def has_add_permission(self, request):
        return False
