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
from django.utils import timezone
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode
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


class ActivationEndpointTests(APITestCase):
    """GET /api/activate/<uidb64>/<token>/ — unlocking the account.

    The frontend calls this from activate.html after reading uid and token from
    the query string, and displays result.message on success and on failure
    (auth.js:263-282). So both cases need that key.
    """

    def setUp(self):
        self.user = User.objects.create_user(
            username="locked@example.com",
            email="locked@example.com",
            password="SecurePass123",
            is_active=False,
        )
        self.uid = urlsafe_base64_encode(force_bytes(self.user.pk))
        self.token = default_token_generator.make_token(self.user)

    def url(self, uid=None, token=None):
        return f"/api/activate/{uid or self.uid}/{token or self.token}/"

    def test_valid_link_returns_200(self):
        response = self.client.get(self.url())
        self.assertEqual(response.status_code, 200)

    def test_valid_link_activates_the_account(self):
        self.client.get(self.url())
        self.user.refresh_from_db()
        self.assertTrue(self.user.is_active)

    def test_success_body_matches_the_documentation(self):
        """Documented: {"message": "Account successfully activated."}."""
        response = self.client.get(self.url())
        self.assertEqual(response.data, {"message": "Account successfully activated."})

    def test_endpoint_is_reachable_without_authentication(self):
        """Nobody can be logged in yet — the account is still locked."""
        response = self.client.get(self.url())
        self.assertNotIn(response.status_code, (401, 403))

    def test_invalid_token_returns_400(self):
        response = self.client.get(self.url(token="not-a-real-token"))
        self.assertEqual(response.status_code, 400)

    def test_invalid_token_leaves_the_account_locked(self):
        self.client.get(self.url(token="not-a-real-token"))
        self.user.refresh_from_db()
        self.assertFalse(self.user.is_active)

    def test_unknown_uid_returns_400(self):
        response = self.client.get(self.url(uid=urlsafe_base64_encode(force_bytes(9999))))
        self.assertEqual(response.status_code, 400)

    def test_malformed_uid_returns_400_instead_of_crashing(self):
        """A hand-edited link must not produce a 500."""
        response = self.client.get(self.url(uid="!!!not-base64!!!"))
        self.assertEqual(response.status_code, 400)

    def test_failure_body_carries_a_message_key(self):
        """auth.js:268 reads result.message on failure too."""
        response = self.client.get(self.url(token="not-a-real-token"))
        self.assertIn("message", response.data)

    def test_clicking_the_link_twice_stays_successful(self):
        """Activation is idempotent, and that is deliberate.

        Django's token hash covers pk, password, last_login, timestamp and email
        — not is_active. Unlocking the account therefore does not invalidate the
        token, and a second click would otherwise report "Activation failed" to
        someone whose account is perfectly fine. Mail clients prefetching links
        and users clicking twice are common enough that the confusing answer
        would cost more than it protects: re-activating an active account
        changes nothing.
        """
        first = self.client.get(self.url())
        second = self.client.get(self.url())
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)

    def test_first_login_invalidates_the_activation_link(self):
        """last_login is part of the hash, so logging in retires the token.

        That is the natural expiry of an activation link, alongside
        PASSWORD_RESET_TIMEOUT (three days by default).
        """
        self.client.get(self.url())
        self.user.refresh_from_db()
        self.user.last_login = timezone.now()
        self.user.save(update_fields=["last_login"])
        self.assertFalse(default_token_generator.check_token(self.user, self.token))

    def test_token_of_another_account_is_rejected(self):
        other = User.objects.create_user(
            username="other@example.com",
            email="other@example.com",
            password="SecurePass123",
            is_active=False,
        )
        other_token = default_token_generator.make_token(other)
        response = self.client.get(self.url(token=other_token))
        self.assertEqual(response.status_code, 400)
        self.user.refresh_from_db()
        self.assertFalse(self.user.is_active)
