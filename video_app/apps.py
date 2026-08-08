from importlib import import_module

from django.apps import AppConfig


class VideoAppConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'video_app'

    def ready(self):
        """Import the signal handlers so their receivers are connected.

        Without this the receivers are never registered and an uploaded video
        stays unconverted, with no error anywhere to explain it. The module is
        imported by name because importing it for its side effect alone reads
        like an unused import.
        """
        import_module(f'{self.name}.signals')
