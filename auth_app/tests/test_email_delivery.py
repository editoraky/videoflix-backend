"""Tests for what happens when the mail server refuses a message.

Every other test in this project runs against Django's in-memory backend, which
never fails. Real SMTP does: providers throttle, credentials expire, hosts go
away. This file replaces the backend with one that raises, because the answers
these endpoints give are part of the contract and must not depend on a service
outside the application.

The password reset case is the sharper one. An unknown address sends no mail at
all and therefore always answers 200, while a known address would answer 500 as
soon as delivery fails. The status code would then reveal which addresses hold
an account — exactly what answering identically is meant to prevent.
"""

from smtplib import SMTPDataError
from unittest.mock import patch

from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase

User = get_user_model()

REGISTER_URL = "/api/register/"
PASSWORD_RESET_URL = "/api/password_reset/"

THROTTLED = SMTPDataError(550, b"5.7.0 Too many emails per second.")


def refusing_mail_server():
    """Patch the send call so every delivery attempt is rejected."""
    return patch(
        "django.core.mail.EmailMultiAlternatives.send",
        side_effect=THROTTLED,
    )


class PasswordResetDeliveryFailureTests(APITestCase):
    """The answer stays the same, whatever the mail server does."""

    def setUp(self):
        self.user = User.objects.create_user(
            username="member@example.com",
            email="member@example.com",
            password="secret123",
        )

    def test_a_refused_delivery_still_answers_200(self):
        with refusing_mail_server():
            response = self.client.post(
                PASSWORD_RESET_URL, {"email": "member@example.com"}, format="json"
            )
        self.assertEqual(response.status_code, 200)

    def test_known_and_unknown_addresses_stay_indistinguishable(self):
        """A 500 for one and a 200 for the other is an account oracle."""
        with refusing_mail_server():
            known = self.client.post(
                PASSWORD_RESET_URL, {"email": "member@example.com"}, format="json"
            )
            unknown = self.client.post(
                PASSWORD_RESET_URL, {"email": "nobody@example.com"}, format="json"
            )
        self.assertEqual(known.status_code, unknown.status_code)
        self.assertEqual(known.content, unknown.content)

    def test_the_failure_is_recorded(self):
        """Silence would leave nobody able to explain the missing email."""
        with refusing_mail_server(), self.assertLogs("auth_app.api.emails", "WARNING"):
            self.client.post(
                PASSWORD_RESET_URL, {"email": "member@example.com"}, format="json"
            )


class RegistrationDeliveryFailureTests(APITestCase):
    """The account exists once it is stored, and the answer has to say so."""

    def payload(self):
        return {
            "email": "newcomer@example.com",
            "password": "SecurePass123!",
            "confirmed_password": "SecurePass123!",
        }

    def test_a_refused_delivery_still_answers_201(self):
        """A 500 would claim the registration failed while the account is there.

        The user would try again and be told the address is already taken.
        """
        with refusing_mail_server():
            response = self.client.post(REGISTER_URL, self.payload(), format="json")
        self.assertEqual(response.status_code, 201)

    def test_the_account_is_stored_and_stays_locked(self):
        with refusing_mail_server():
            self.client.post(REGISTER_URL, self.payload(), format="json")
        user = User.objects.get(email="newcomer@example.com")
        self.assertFalse(user.is_active)

    def test_the_failure_is_recorded(self):
        with refusing_mail_server(), self.assertLogs("auth_app.api.emails", "WARNING"):
            self.client.post(REGISTER_URL, self.payload(), format="json")
