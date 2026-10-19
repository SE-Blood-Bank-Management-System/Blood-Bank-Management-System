from django.urls import path
from . import views

app_name = 'core'

urlpatterns = [
    path('', views.home, name='home'),
    path('availability/', views.public_availability, name='public_availability'),
    path('about/', views.about, name='about'),
]
