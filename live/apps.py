from django.apps import AppConfig


class LiveConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'live'

    def ready(self):
        import os
        if os.environ.get("RUN_MAIN") == "true":
            from datetime import timedelta

            from django.utils.timezone import now

            from .models import Donator, Gift

            # Optional: Only delete if older than 12 hours
            cutoff = now() - timedelta(hours=12)
            Donator.objects.all().delete()
            Gift.objects.all().delete()
            print("[INIT] Donator & Gift tables cleared")