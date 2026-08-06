"""Database models for authentication."""

from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """A Videoflix account, identified by its email address.

    The frontend never sends a username: registration posts email, password and
    confirmed_password, login posts email and password. Registration therefore
    stores the address in both fields. That also matches the documented login
    response, which returns "username": "user@example.com".

    The username field is kept deliberately. backend.entrypoint.sh belongs to the
    given Docker setup and creates the superuser with
    create_superuser(username=...) after filtering on filter(username=...).
    Removing the field would abort every container start with a FieldError.

    Two inherited restrictions had to be lifted, because the field now carries an
    email address:

      * max_length was 150, while an EmailField accepts up to 254 characters
      * UnicodeUsernameValidator permits only [\\w.@+-] and would reject legal
        addresses containing characters such as ! or %

    is_active keeps its inherited default of True. Accounts are deactivated by the
    registration serializer, not by the model — otherwise the superuser created on
    container start would be locked out of the admin.
    """

    username = models.CharField(max_length=254, unique=True, validators=[])
    email = models.EmailField(unique=True)

    def __str__(self):
        return self.email
