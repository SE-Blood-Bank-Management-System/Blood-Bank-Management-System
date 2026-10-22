from django.urls import path
from . import views

app_name = 'donors'

urlpatterns = [
    path('dashboard/', views.dashboard, name='dashboard'),
    path('history/', views.donation_history, name='history'),
    path('<int:donor_id>/profile/', views.donor_profile, name='profile'),
    path('<int:donor_id>/history/', views.donation_history, name='donor_history'),
    path('eligibility/', views.eligibility_check, name='eligibility'),
]
