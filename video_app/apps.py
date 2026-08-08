from django.apps import AppConfig


class VideoAppConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'video_app'

    def ready(self):
        """Import the signal handlers so they are connected.

        Without this the receivers are never registered and an uploaded video
        stays unconverted — with no error anywhere to explain it.
        """
        from . import signals  # noqa: F401
