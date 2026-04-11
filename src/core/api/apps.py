from django.apps import AppConfig


class ApiConfig(AppConfig):
    name = 'api'
    
    def ready(self):
        """Registrar signals cuando la app está lista."""
        import api.Signals.signals  # noqa: F401
        import api.Signals.profile_photo_signals  # noqa: F401
