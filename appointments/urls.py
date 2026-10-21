from django.urls import path
from . import views

app_name = 'appointments'

urlpatterns = [
    path('', views.appointment_list, name='list'),
    path('book/', views.book_appointment, name='book'),
    path('<int:pk>/', views.appointment_detail, name='detail'),
    path('<int:pk>/reschedule/', views.reschedule_appointment, name='reschedule'),
    path('<int:pk>/cancel/', views.cancel_appointment, name='cancel'),
    # REST API endpoints (SAD Section 4.3)
    path('api/slots/', views.api_slots, name='api_slots'),
    path('api/', views.api_appointments, name='api_appointments'),
    path('api/<int:pk>/', views.api_appointment_detail, name='api_appointment_detail'),
]
