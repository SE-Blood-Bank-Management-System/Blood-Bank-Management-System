"""
URL configuration for inventory app.
SRS BBMS-F-020 to BBMS-F-023, BBMS-F-026 to BBMS-F-039.
"""
from django.urls import path
from . import views

app_name = 'inventory'

urlpatterns = [
    path('', views.inventory_dashboard, name='dashboard'),
    path('api/', views.api_inventory, name='api_inventory'),
    path('collection/record/', views.record_blood_collection, name='record_collection'),
    path('quarantine/', views.quarantine_list, name='quarantine'),
    path('blood-units/<str:bag_id>/', views.blood_unit_detail, name='unit_detail'),
    path('blood-units/<str:bag_id>/status-history/', views.status_history, name='status_history'),
    path('blood-units/<str:bag_id>/blood-group/', views.update_unit_blood_group, name='update_blood_group'),
    path('blood-units/<str:bag_id>/serology/', views.record_serology_tests, name='record_serology'),
    path('api/blood-units/<str:bag_id>/serology/', views.api_record_serology, name='api_record_serology'),
    # FEFO Allocation, Dispatch Manifests and Fulfilment (Issue #37)
    path(
        'requisitions/<int:requisition_pk>/allocate/',
        views.allocate_requisition_view,
        name='allocate_requisition'
    ),
    path(
        'requisitions/<int:requisition_pk>/dispatch/',
        views.dispatch_requisition_view,
        name='dispatch_requisition'
    ),
    path('manifests/<str:manifest_id>/', views.manifest_detail_view, name='manifest_detail'),
    path(
        'api/requisitions/<int:requisition_pk>/suggestions/',
        views.api_fefo_suggestions,
        name='api_fefo_suggestions'
    ),
    path(
        'api/requisitions/<int:requisition_pk>/allocate/',
        views.api_allocate_units,
        name='api_allocate_units'
    ),
    path(
        'api/requisitions/<int:requisition_pk>/dispatch/',
        views.api_dispatch_units,
        name='api_dispatch_units'
    ),
    path('api/manifests/<str:manifest_id>/', views.api_manifest_detail, name='api_manifest_detail'),
]

