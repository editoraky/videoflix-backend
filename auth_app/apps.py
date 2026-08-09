"""App configuration for authentication."""

from django.apps import AppConfig


class AuthAppConfig(AppConfig):
    """Registers the app that owns the user model and the auth endpoints."""

    default_auto_field = 'django.db.models.BigAutoField'
    name = 'auth_app'
