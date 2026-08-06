"""Tests for the custom user model.

The model has to satisfy two masters at once: the API contract, which knows only
email addresses, and backend.entrypoint.sh, which is part of the given Docker
setup and creates the superuser through the username field.
"""

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.test import TestCase

User = get_user_model()


class CustomUserModelTests(TestCase):
    """Structural guarantees of the user model."""

    def test_project_uses_the_custom_user_model(self):
        """AUTH_USER_MODEL must point at our model, not django.contrib.auth.User."""
        self.assertEqual(User._meta.label, "auth_app.User")

    def test_email_is_unique_on_database_level(self):
        """A duplicate email must fail in the database, not only in a serializer.

        Registration rejects known addresses, but a constraint that lives only in
        validation code is one forgotten call away from being bypassed.
        """
        User.objects.create_user(
            username="taken@example.com", email="taken@example.com", password="secret123"
        )
        with self.assertRaises(IntegrityError):
            User.objects.create_user(
                username="other", email="taken@example.com", password="secret123"
            )

    def test_str_returns_the_email(self):
        """Admin lists and log lines should show the address, not "User object (1)"."""
        user = User.objects.create_user(
            username="a@example.com", email="a@example.com", password="secret123"
        )
        self.assertEqual(str(user), "a@example.com")


class EntrypointCompatibilityTests(TestCase):
    """Reproduces exactly what backend.entrypoint.sh does on every container start.

    The file must not be modified, so these two calls have to keep working.
    A failure here means the container aborts before Django ever serves a request.
    """

    def test_create_superuser_accepts_the_three_keywords(self):
        """entrypoint line 35: create_superuser(username=..., email=..., password=...)."""
        user = User.objects.create_superuser(
            username="admin", email="admin@example.com", password="adminpassword"
        )
        self.assertTrue(user.is_superuser)
        self.assertTrue(user.is_staff)

    def test_users_can_be_filtered_by_username(self):
        """entrypoint line 32: User.objects.filter(username=...).exists()."""
        User.objects.create_superuser(
            username="admin", email="admin@example.com", password="adminpassword"
        )
        self.assertTrue(User.objects.filter(username="admin").exists())

    def test_superuser_is_active_and_can_reach_the_admin(self):
        """Registration deactivates accounts, but the superuser must stay usable.

        is_active therefore keeps its inherited default of True; only the
        registration serializer sets it to False.
        """
        user = User.objects.create_superuser(
            username="admin", email="admin@example.com", password="adminpassword"
        )
        self.assertTrue(user.is_active)


class UsernameFieldWidenedTests(TestCase):
    """The inherited username field is too narrow and too strict for an email.

    Both defects only surface with unusual addresses — that is, during review.
    """

    def test_username_holds_an_email_longer_than_150_characters(self):
        """AbstractUser caps username at 150, while EmailField allows 254."""
        long_email = "a" * 200 + "@example.com"
        user = User.objects.create_user(
            username=long_email, email=long_email, password="secret123"
        )
        self.assertEqual(User.objects.get(pk=user.pk).username, long_email)

    def test_username_accepts_characters_the_default_validator_rejects(self):
        """UnicodeUsernameValidator allows only [\\w.@+-]; RFC 5322 allows more."""
        unusual_email = "first!last%tag@example.com"
        user = User(username=unusual_email, email=unusual_email)
        user.set_password("secret123")
        try:
            user.full_clean()
        except ValidationError as error:
            self.fail(f"A legal email address was rejected: {error}")


class UserAdminTests(TestCase):
    """Videos are uploaded through the admin, so it has to work for users too."""

    def setUp(self):
        self.admin = User.objects.create_superuser(
            username="admin", email="admin@example.com", password="adminpassword"
        )
        self.client.force_login(self.admin)

    def test_user_changelist_is_reachable(self):
        """The model must be registered, otherwise the admin returns 404."""
        response = self.client.get("/admin/auth_app/user/")
        self.assertEqual(response.status_code, 200)

    def test_add_form_offers_the_email_field(self):
        """UserAdmin's default add form asks only for username and passwords.

        Our email field is required and unique, so without it in add_fieldsets
        every attempt to create a user through the admin fails.
        """
        response = self.client.get("/admin/auth_app/user/add/")
        self.assertContains(response, 'name="email"')
