"""Admin configuration for authentication."""

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import User


@admin.register(User)
class VideoflixUserAdmin(UserAdmin):
    """Django's UserAdmin, reordered around the email address.

    The inherited add_fieldsets asks only for username and the two password
    fields. Our email is required and unique, so it has to be added there —
    otherwise creating a user through the admin fails on the database
    constraint before the form is ever saved.
    """

    list_display = ("email", "username", "is_active", "is_staff", "date_joined")
    list_filter = ("is_active", "is_staff", "is_superuser")
    search_fields = ("email", "username")
    ordering = ("-date_joined",)

    add_fieldsets = UserAdmin.add_fieldsets + (
        (None, {"fields": ("email",)}),
    )
