"""
Admin registration for Blood Bank Inventory models.
SRS BBMS-F-020 to BBMS-F-023, BBMS-F-060.
"""
from django.contrib import admin
from .models import BloodUnit, SerologyTest


class SerologyTestInline(admin.TabularInline):
    model = SerologyTest
    extra = 0
    readonly_fields = ('tested_at',)


@admin.register(BloodUnit)
class BloodUnitAdmin(admin.ModelAdmin):
    inlines = [SerologyTestInline]
    list_display = (
        'bag_id',
        'blood_group',
        'status',
        'component_type',
        'volume_ml',
        'donor',
        'collection_date',
        'expiry_date',
        'lab_confirmed_by',
        'lab_confirmed_at',
    )
    list_filter = ('blood_group', 'status', 'component_type', 'location')
    search_fields = ('bag_id', 'donor__email', 'donor__username', 'blood_group_notes')
    readonly_fields = ('lab_confirmed_at', 'created_at', 'updated_at')
    fieldsets = (
        ('Blood Unit Identification', {
            'fields': ('bag_id', 'parent_unit', 'donor')
        }),
        ('Blood Group & Laboratory Confirmation', {
            'fields': ('blood_group', 'lab_confirmed_by', 'lab_confirmed_at', 'blood_group_notes')
        }),
        ('Inventory & Lifecycle', {
            'fields': ('status', 'component_type', 'volume_ml', 'location', 'collection_date', 'expiry_date')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


@admin.register(SerologyTest)
class SerologyTestAdmin(admin.ModelAdmin):
    list_display = ('blood_unit', 'test_type', 'result', 'tested_by', 'tested_at')
    list_filter = ('test_type', 'result', 'tested_at')
    search_fields = ('blood_unit__bag_id', 'tested_by__username', 'notes')
    readonly_fields = ('tested_at',)

