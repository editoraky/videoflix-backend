"""Tests for the activation email.

The link in that email is the single most error-prone detail of the whole
project: it must point at the FRONTEND and carry uid and token as query
parameters, because ui_helper.js:116-125 reads them with URLSearchParams.
A link pointing at the backend endpoint would show raw JSON instead of a page.
"""

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.core import mail
from django.utils.encoding import force_str
from django.utils.http import urlsafe_base64_decode
from rest_framework.test import APITestCase

User = get_user_model()

REGISTER_URL = "/api/register/"

PAYLOAD = {
    "email": "new@example.com",
    "password": "SecurePass123",
    "confirmed_password": "SecurePass123",
}


class ActivationEmailTests(APITestCase):
    """What registration has to put in the user's inbox."""

    def setUp(self):
        self.client.post(REGISTER_URL, PAYLOAD, format="json")
        self.message = mail.outbox[0] if mail.outbox else None
        self.user = User.objects.get(email="new@example.com")

    def test_registration_sends_exactly_one_email(self):
        """Checklist US 1: a confirmation email is sent after registration."""
        self.assertEqual(len(mail.outbox), 1)

    def test_email_goes_to_the_registered_address(self):
        self.assertEqual(self.message.to, ["new@example.com"])

    def test_email_carries_an_html_alternative(self):
        """Checklist US 1 refers to a design template, which needs HTML."""
        alternatives = [content_type for _, content_type in self.message.alternatives]
        self.assertIn("text/html", alternatives)

    def test_link_points_at_the_frontend(self):
        """Contract C-2: the mail links to the frontend, never to the API."""
        self.assertIn(settings.FRONTEND_BASE_URL, self.message.body)
        self.assertIn("/pages/auth/activate.html", self.message.body)

    def test_link_does_not_point_at_the_backend_endpoint(self):
        """A link to /api/activate/ would render raw JSON in the browser."""
        self.assertNotIn("/api/activate/", self.message.body)

    def test_link_carries_uid_and_token_as_query_parameters(self):
        """ui_helper.js reads them with URLSearchParams, not from the path."""
        self.assertIn("?uid=", self.message.body)
        self.assertIn("&token=", self.message.body)

    def test_plain_text_link_is_not_html_escaped(self):
        """Django escapes template variables even in .txt templates.

        That turns the separator into "&amp;token=", and URLSearchParams then
        reads a parameter called "amp;token" while "token" stays empty — the
        activation page rejects the link as invalid. Nothing about the address
        looks wrong at a glance, which is what makes it expensive to find.
        """
        self.assertNotIn("&amp;", self.message.body)

    def test_uid_decodes_back_to_the_new_account(self):
        uid = self.message.body.split("?uid=")[1].split("&token=")[0]
        self.assertEqual(force_str(urlsafe_base64_decode(uid)), str(self.user.pk))

    def test_token_is_accepted_by_the_generator(self):
        token = self.message.body.split("&token=")[1].split()[0].strip()
        self.assertTrue(default_token_generator.check_token(self.user, token))

    def test_html_body_contains_the_same_link(self):
        html = self.message.alternatives[0][0]
        self.assertIn("/pages/auth/activate.html?uid=", html)

    def test_failed_registration_sends_no_email(self):
        """A rejected payload must not put anything in an inbox."""
        mail.outbox.clear()
        self.client.post(
            REGISTER_URL,
            {**PAYLOAD, "email": "other@example.com", "confirmed_password": "Mismatch123"},
            format="json",
        )
        self.assertEqual(len(mail.outbox), 0)
