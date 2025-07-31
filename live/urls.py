from django.urls import path

from .views import live_stream, recent_gifts

urlpatterns = [
    path('stream/<str:username>/', live_stream, name='live-events'),
    path('recent/', recent_gifts, name='recent-gifts'),
]