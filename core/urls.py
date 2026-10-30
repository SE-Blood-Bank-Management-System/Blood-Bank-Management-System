from django.urls import path
from . import views

app_name = 'core'

urlpatterns = [
    path('', views.home, name='home'),
    path('availability/', views.public_availability, name='public_availability'),
    path('about/', views.about, name='about'),
    path('audit-log/', views.audit_log_view, name='audit_log'),
    # System Reports & CSV Exports (BBMS-F-064, BBMS-F-065, BBMS-F-066)
    path('reports/', views.reports_dashboard, name='reports_dashboard'),
    path('reports/inventory/csv/', views.export_inventory_csv, name='export_inventory_csv'),
    path('reports/donations/csv/', views.export_donations_csv, name='export_donations_csv'),
    path('reports/requisitions/csv/', views.export_requisitions_csv, name='export_requisitions_csv'),
    path('api/reports/', views.api_reports, name='api_reports'),
]
