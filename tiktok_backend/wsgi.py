import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'tiktok_backend.settings')

application = get_wsgi_application()

# === Workaround: allow connection object to be used across threads/greenlets ===
# This prevents Django from raising DatabaseError when other threads/greenlets
# try to close or reuse a connection object created elsewhere.
# WARNING: This is a workaround — it's safe enough for many apps, but can hide
# concurrency issues. See long-term fixes below.
try:
    from django.db import connection
    connection.set_allow_thread_sharing(True)
except Exception:
    # If anything goes wrong, don't block app startup.
    import logging
    logging.getLogger(__name__).exception("Failed to set allow_thread_sharing")
