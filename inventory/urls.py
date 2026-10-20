"""
URL configuration for inventory app.
SRS BBMS-F-020 to BBMS-F-023, BBMS-F-026 to BBMS-F-039.
"""
from django.urls import path
from . import views

app_name = 'inventory'

urlpatterns = [
    path('', views.inventory_dashboard, name='dashboard'),
    path('quarantine/', views.quarantine_list, name='quarantine'),
    path('blood-units/<str:bag_id>/', views.blood_unit_detail, name='unit_detail'),
    path('blood-units/<str:bag_id>/blood-group/', views.update_unit_blood_group, name='update_blood_group'),
]
