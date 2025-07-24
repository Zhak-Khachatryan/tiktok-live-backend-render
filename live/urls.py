from django.urls import path
from .views import live_events

urlpatterns = [
    path('sse/', live_events, name='live-events'),
]