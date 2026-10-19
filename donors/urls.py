from django.urls import path
from . import views

app_name = 'donors'

urlpatterns = [
    path('dashboard/', views.dashboard, name='dashboard'),
    path('history/', views.donation_history, name='history'),
    path('eligibility/', views.eligibility_check, name='eligibility'),
]
