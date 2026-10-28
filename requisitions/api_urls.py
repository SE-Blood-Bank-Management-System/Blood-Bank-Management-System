from django.urls import path

from . import api

app_name = 'requisition_api'

urlpatterns = [
    path('', api.requests, name='list'),
    path('<int:pk>/', api.detail, name='detail'),
    path('<int:pk>/priority/', api.priority, name='priority'),
    path('<int:pk>/review/', api.review, name='review'),
    path('<int:pk>/cross-match/', api.cross_match, name='cross_match'),
]
