"""Tests for the registration serializer.

Field names are not a design choice — they are whatever register.html sends:
name="email", name="password", name="confirmed_password", name="privacy_policy".
"""

from django.contrib.auth import get_user_model
from django.test import TestCase

from auth_app.api.serializers import RegistrationSerializer

User = get_user_model()


def payload(**overrides):
    """Return a valid registration payload, optionally overridden."""
    data = {
        "email": "new@example.com",
        "password": "SecurePass123",
        "confirmed_password": "SecurePass123",
    }
    data.update(overrides)
    return data


class RegistrationSerializerValidPayloadTests(TestCase):
    """What a correct registration has to produce."""

    def test_valid_payload_is_accepted(self):
        serializer = RegistrationSerializer(data=payload())
        self.assertTrue(serializer.is_valid(), serializer.errors)

    def test_new_account_starts_inactive(self):
        """Checklist US 1: the account must be unlocked before the first login."""
        serializer = RegistrationSerializer(data=payload())
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        self.assertFalse(user.is_active)

    def test_username_is_set_to_the_email(self):
        """The frontend never sends a username, but entrypoint.sh needs the field.

        Storing the address in both fields also matches the documented login
        response, which returns "username": "user@example.com".
        """
        serializer = RegistrationSerializer(data=payload())
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        self.assertEqual(user.username, "new@example.com")

    def test_password_is_stored_hashed(self):
        serializer = RegistrationSerializer(data=payload())
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        self.assertNotEqual(user.password, "SecurePass123")
        self.assertTrue(user.check_password("SecurePass123"))

    def test_password_fields_are_write_only(self):
        """Neither password may ever appear in a response body."""
        serializer = RegistrationSerializer(data=payload())
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        rendered = RegistrationSerializer(user).data
        self.assertNotIn("password", rendered)
        self.assertNotIn("confirmed_password", rendered)

    def test_extra_privacy_policy_field_is_tolerated(self):
        """register.html submits the consent checkbox as privacy_policy="on".

        getFormData() collects every named input, so the field arrives whether
        the API documentation lists it or not. Rejecting it would break the form.
        """
        serializer = RegistrationSerializer(data=payload(privacy_policy="on"))
        self.assertTrue(serializer.is_valid(), serializer.errors)


class RegistrationSerializerRejectionTests(TestCase):
    """What has to be refused — and how little the message may reveal."""

    GENERIC = "Please check your input and try again."

    def test_mismatched_passwords_are_rejected(self):
        serializer = RegistrationSerializer(
            data=payload(confirmed_password="SomethingElse123")
        )
        self.assertFalse(serializer.is_valid())

    def test_duplicate_email_is_rejected(self):
        User.objects.create_user(
            username="new@example.com", email="new@example.com", password="SecurePass123"
        )
        serializer = RegistrationSerializer(data=payload())
        self.assertFalse(serializer.is_valid())

    def test_malformed_email_is_rejected(self):
        serializer = RegistrationSerializer(data=payload(email="not-an-address"))
        self.assertFalse(serializer.is_valid())

    def test_short_password_is_rejected(self):
        """The frontend requires more than 7 characters (auth.js:110)."""
        serializer = RegistrationSerializer(data=payload(password="abc", confirmed_password="abc"))
        self.assertFalse(serializer.is_valid())

    def test_every_rejection_returns_the_same_generic_message(self):
        """Checklist US 1: messages stay generic for security reasons.

        A specific "email already exists" would let anyone probe which addresses
        hold an account. Since all failures share one message, a duplicate address
        is indistinguishable from a typo in the password.
        """
        User.objects.create_user(
            username="taken@example.com", email="taken@example.com", password="SecurePass123"
        )
        cases = {
            "duplicate email": payload(email="taken@example.com"),
            "mismatched passwords": payload(confirmed_password="Other123456"),
            "malformed email": payload(email="not-an-address"),
            "short password": payload(password="abc", confirmed_password="abc"),
        }
        for label, data in cases.items():
            with self.subTest(case=label):
                serializer = RegistrationSerializer(data=data)
                self.assertFalse(serializer.is_valid())
                messages = [str(m) for values in serializer.errors.values() for m in values]
                self.assertEqual(messages, [self.GENERIC])

    def test_message_never_mentions_the_email_address(self):
        """The response must not echo which address was tried."""
        User.objects.create_user(
            username="taken@example.com", email="taken@example.com", password="SecurePass123"
        )
        serializer = RegistrationSerializer(data=payload(email="taken@example.com"))
        serializer.is_valid()
        self.assertNotIn("taken@example.com", str(serializer.errors))
