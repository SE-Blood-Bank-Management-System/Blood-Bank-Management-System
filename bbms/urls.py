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
from inventory import views as inventory_views

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('core.urls', namespace='core')),
    path('accounts/', include('accounts.urls', namespace='accounts')),
    path('donors/', include('donors.urls', namespace='donors')),
    path('appointments/', include('appointments.urls', namespace='appointments')),
    path('inventory/', include('inventory.urls', namespace='inventory')),
    # REST API endpoints (SAD Section 4.3)
    path(
        'api/blood-units/<str:bag_id>/blood-group/',
        inventory_views.api_update_unit_blood_group,
        name='api_blood_unit_blood_group'
    ),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
