"""
URL configuration for BBMS project.

Routes URLs to apps:
- core: landing, public availability, static pages
- accounts: authentication, registration, user management
- donors: donor profiles, eligibility, history
- appointments: scheduling, capacity, rescheduling
- inventory: blood units, testing, quarantine, FEFO inventory
"""
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from appointments import views as appointment_views
from inventory import views as inventory_views

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('core.urls', namespace='core')),
    path('accounts/', include('accounts.urls', namespace='accounts')),
    path('donors/', include('donors.urls', namespace='donors')),
    path('api/donors/', include('donors.api_urls', namespace='donor_api')),
    path('appointments/', include('appointments.urls', namespace='appointments')),
    path('inventory/', include('inventory.urls', namespace='inventory')),
    path('requisitions/', include('requisitions.urls', namespace='requisitions')),
    path('api/requests/', include('requisitions.api_urls', namespace='requisition_api')),
    # REST API endpoints (SAD Section 4.3)
    path('api/inventory/', inventory_views.api_inventory, name='api_root_inventory'),
    path('api/quarantine/', inventory_views.quarantine_list, name='api_quarantine'),
    path('api/blood-units/<str:bag_id>/status-history/', inventory_views.status_history, name='api_status_history'),
    path(
        'api/blood-units/<str:bag_id>/blood-group/',
        inventory_views.api_update_unit_blood_group,
        name='api_blood_unit_blood_group'
    ),
    path(
        'api/blood-units/<str:bag_id>/serology/',
        inventory_views.api_record_serology,
        name='api_blood_unit_serology'
    ),

    path(
        'api/appointments/slots/',
        appointment_views.api_slots,
        name='api_root_appointment_slots'
    ),
    path(
        'api/appointments/',
        appointment_views.api_appointments,
        name='api_root_appointments'
    ),
    path(
        'api/appointments/<int:pk>/',
        appointment_views.api_appointment_detail,
        name='api_root_appointment_detail'
    ),
    # Allocation & Dispatch API endpoints (SAD Section 4.3, Issue #37)
    path(
        'api/requisitions/<int:requisition_pk>/suggestions/',
        inventory_views.api_fefo_suggestions,
        name='api_root_fefo_suggestions'
    ),
    path(
        'api/requisitions/<int:requisition_pk>/allocate/',
        inventory_views.api_allocate_units,
        name='api_root_allocate_units'
    ),
    path(
        'api/requisitions/<int:requisition_pk>/dispatch/',
        inventory_views.api_dispatch_units,
        name='api_root_dispatch_units'
    ),
    path(
        'api/manifests/<str:manifest_id>/',
        inventory_views.api_manifest_detail,
        name='api_root_manifest_detail'
    ),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
