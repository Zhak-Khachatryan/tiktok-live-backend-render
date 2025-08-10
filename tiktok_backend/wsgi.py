"""
WSGI config for tiktok_backend project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/5.2/howto/deployment/wsgi/
"""

import os

from django.core.wsgi import get_wsgi_application
from django.db import close_old_connections

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'tiktok_backend.settings')

class CloseDBConnectionMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
    def __call__(self, request):
        response = self.get_response(request)
        close_old_connections()
        return response
    
application = get_wsgi_application()
