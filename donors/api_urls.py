from django.urls import path
from . import api

app_name = 'donor_api'

urlpatterns = [
    path('me', api.profile, name='profile'),
    path('me/donations', api.donations, name='donations'),
    path('me/eligibility', api.eligibility, name='eligibility'),
]
