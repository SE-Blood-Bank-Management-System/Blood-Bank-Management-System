from django.contrib import admin
from .models import BloodBankLocation, AppointmentSlot, Appointment


@admin.register(BloodBankLocation)
class BloodBankLocationAdmin(admin.ModelAdmin):
    list_display = ('name', 'city', 'contact_number', 'is_active', 'created_at')
    list_filter = ('is_active', 'city')
    search_fields = ('name', 'address', 'city')


@admin.register(AppointmentSlot)
class AppointmentSlotAdmin(admin.ModelAdmin):
    list_display = ('location', 'date', 'time_label', 'booked_count', 'max_capacity', 'is_active')
    list_filter = ('location', 'date', 'is_active')
    search_fields = ('location__name', 'date')
    date_hierarchy = 'date'


@admin.register(Appointment)
class AppointmentAdmin(admin.ModelAdmin):
    list_display = ('booking_reference', 'donor', 'location', 'date', 'time_slot', 'status', 'created_at')
    list_filter = ('status', 'location', 'date')
    search_fields = ('booking_reference', 'donor__username', 'donor__email', 'location__name')
    readonly_fields = ('booking_reference', 'created_at', 'updated_at', 'cancelled_at')
    date_hierarchy = 'date'
