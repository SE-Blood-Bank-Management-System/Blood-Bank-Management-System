from django.urls import path
from . import views

app_name = 'accounts'

urlpatterns = [
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('register/donor/', views.register_donor, name='register_donor'),
    path('register/hospital/', views.register_hospital, name='register_hospital'),
    path('profile/', views.profile, name='profile'),
]
