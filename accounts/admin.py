from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import User


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (
        ('BBMS Role & Profile', {'fields': ('role', 'phone', 'is_approved')}),
    )
    add_fieldsets = UserAdmin.add_fieldsets + (
        ('BBMS Role & Profile', {'fields': ('role', 'phone', 'is_approved')}),
    )
    list_display = ('username', 'email', 'first_name', 'last_name', 'role', 'is_approved', 'is_active', 'is_staff')
    list_filter = ('role', 'is_approved', 'is_staff', 'is_active')
    search_fields = ('username', 'email', 'first_name', 'last_name', 'phone')
