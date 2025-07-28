from django.urls import path

from .views import live_events, recent_gifts

urlpatterns = [
    path('sse/', live_events, name='live-events'),
    path('recent/', recent_gifts, name='recent-gifts'),
]