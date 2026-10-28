from django.urls import path

from . import views

app_name = 'requisitions'

urlpatterns = [
    path('', views.request_list, name='list'),
    path('new/', views.create, name='create'),
    path('stat-alerts/', views.stat_alerts, name='stat_alerts'),
    path('<int:pk>/', views.detail, name='detail'),
    path('<int:pk>/review/', views.review, name='review'),
    path('<int:pk>/priority/', views.priority, name='priority'),
    path('<int:pk>/cross-match/', views.cross_match, name='cross_match'),
]
