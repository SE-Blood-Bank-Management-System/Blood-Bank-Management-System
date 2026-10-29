from django.contrib import admin

from .models import DeliveryConfirmation, Requisition, RequisitionEvent, RequisitionFulfilment


class ReadOnlyRequestAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Requisition)
class RequisitionAdmin(ReadOnlyRequestAdmin):
    list_display = ('requisition_id', 'hospital', 'blood_group', 'component_type', 'quantity', 'status', 'is_stat')
    list_filter = ('status', 'is_stat', 'component_type', 'blood_group')
    search_fields = ('requisition_id', 'hospital__hospital_name')
    list_select_related = ('hospital',)


@admin.register(RequisitionEvent)
class RequisitionEventAdmin(ReadOnlyRequestAdmin):
    list_display = ('requisition', 'action', 'actor_label', 'created_at')
    list_filter = ('action', 'created_at')
    list_select_related = ('requisition',)


@admin.register(RequisitionFulfilment)
class RequisitionFulfilmentAdmin(ReadOnlyRequestAdmin):
    list_display = ('requisition', 'blood_unit', 'recorded_by', 'recorded_at')
    list_select_related = ('requisition', 'blood_unit', 'recorded_by')


@admin.register(DeliveryConfirmation)
class DeliveryConfirmationAdmin(ReadOnlyRequestAdmin):
    list_display = ('fulfilment', 'receiver_label', 'received_at')
    list_select_related = ('fulfilment__blood_unit', 'received_by')
