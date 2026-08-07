"""Tests for the password reset flow.

Two endpoints, one feature: requesting the link and redeeming it.

Contract C-12: POST /api/password_reset/ answers 200 for every address, known
or not. Checklist US 4 forbids revealing whether an account exists, so a 404
here would be a bug, not a nicety.
"""

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.core import mail
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from rest_framework.test import APITestCase

User = get_user_model()

RESET_URL = "/api/password_reset/"
OLD_PASSWORD = "SecurePass123"
NEW_PASSWORD = "BrandNewPass456"


def create_member(email="member@example.com"):
    return User.objects.create_user(
        username=email, email=email, password=OLD_PASSWORD, is_active=True
    )


class PasswordResetRequestTests(APITestCase):
    """Requesting the link — and revealing nothing in the process."""

    def setUp(self):
        self.user = create_member()

    def test_known_address_returns_200(self):
        response = self.client.post(RESET_URL, {"email": self.user.email}, format="json")
        self.assertEqual(response.status_code, 200)

    def test_unknown_address_also_returns_200(self):
        """Contract C-12: the answer must not depend on whether the account exists."""
        response = self.client.post(RESET_URL, {"email": "nobody@example.com"}, format="json")
        self.assertEqual(response.status_code, 200)

    def test_both_answers_are_byte_for_byte_identical(self):
        """Any difference at all turns the form into an account lookup."""
        known = self.client.post(RESET_URL, {"email": self.user.email}, format="json")
        unknown = self.client.post(RESET_URL, {"email": "nobody@example.com"}, format="json")
        self.assertEqual(known.data, unknown.data)

    def test_response_body_matches_the_documentation(self):
        response = self.client.post(RESET_URL, {"email": self.user.email}, format="json")
        self.assertEqual(
            response.data["detail"], "An email has been sent to reset your password."
        )

    def test_endpoint_is_reachable_without_authentication(self):
        response = self.client.post(RESET_URL, {"email": self.user.email}, format="json")
        self.assertNotIn(response.status_code, (401, 403))

    def test_known_address_receives_an_email(self):
        self.client.post(RESET_URL, {"email": self.user.email}, format="json")
        self.assertEqual(len(mail.outbox), 1)

    def test_unknown_address_receives_nothing(self):
        """Identical answer, but no mail to an address that holds no account."""
        self.client.post(RESET_URL, {"email": "nobody@example.com"}, format="json")
        self.assertEqual(len(mail.outbox), 0)

    def test_inactive_account_receives_nothing(self):
        """An unconfirmed account has to finish activation, not reset a password."""
        self.user.is_active = False
        self.user.save(update_fields=["is_active"])
        self.client.post(RESET_URL, {"email": self.user.email}, format="json")
        self.assertEqual(len(mail.outbox), 0)

    def test_link_points_at_the_frontend_confirm_page(self):
        """Contract C-2 / F-11: never at the API, or the user sees raw JSON."""
        self.client.post(RESET_URL, {"email": self.user.email}, format="json")
        body = mail.outbox[0].body
        self.assertIn(settings.FRONTEND_BASE_URL, body)
        self.assertIn("/pages/auth/confirm_password.html", body)
        self.assertNotIn("/api/password_confirm/", body)

    def test_link_carries_uid_and_token_as_query_parameters(self):
        self.client.post(RESET_URL, {"email": self.user.email}, format="json")
        self.assertIn("?uid=", mail.outbox[0].body)
        self.assertIn("&token=", mail.outbox[0].body)

    def test_plain_text_link_is_not_html_escaped(self):
        """Fallstrick F-10: Django escapes variables even in .txt templates."""
        self.client.post(RESET_URL, {"email": self.user.email}, format="json")
        self.assertNotIn("&amp;", mail.outbox[0].body)

    def test_email_carries_an_html_alternative(self):
        self.client.post(RESET_URL, {"email": self.user.email}, format="json")
        types = [content_type for _, content_type in mail.outbox[0].alternatives]
        self.assertIn("text/html", types)

    def test_malformed_address_returns_200_as_well(self):
        """Even a rejected format must not stand out from a successful request."""
        response = self.client.post(RESET_URL, {"email": "not-an-address"}, format="json")
        self.assertEqual(response.status_code, 200)


class PasswordResetConfirmTests(APITestCase):
    """Redeeming the link and setting the new password."""

    def setUp(self):
        self.user = create_member()
        self.uid = urlsafe_base64_encode(force_bytes(self.user.pk))
        self.token = default_token_generator.make_token(self.user)

    def url(self, uid=None, token=None):
        return f"/api/password_confirm/{uid or self.uid}/{token or self.token}/"

    def post(self, url=None, **overrides):
        data = {"new_password": NEW_PASSWORD, "confirm_password": NEW_PASSWORD}
        data.update(overrides)
        return self.client.post(url or self.url(), data, format="json")

    def test_valid_request_returns_200(self):
        self.assertEqual(self.post().status_code, 200)

    def test_response_body_matches_the_documentation(self):
        self.assertEqual(
            self.post().data["detail"], "Your Password has been successfully reset."
        )

    def test_password_is_actually_changed(self):
        self.post()
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(NEW_PASSWORD))

    def test_old_password_stops_working(self):
        """The checklist requires the old password to be gone, not merely shadowed."""
        self.post()
        self.user.refresh_from_db()
        self.assertFalse(self.user.check_password(OLD_PASSWORD))

    def test_endpoint_is_reachable_without_authentication(self):
        """Whoever forgot their password cannot be logged in."""
        self.assertNotIn(self.post().status_code, (401, 403))

    def test_link_cannot_be_used_a_second_time(self):
        """Fallstrick F-24: the password hash is part of the token signature.

        Changing it invalidates the token by itself — unlike the activation
        link, this one really is single-use.
        """
        self.assertEqual(self.post().status_code, 200)
        self.assertEqual(self.post().status_code, 400)

    def test_mismatched_passwords_are_rejected(self):
        self.assertEqual(self.post(confirm_password="SomethingElse789").status_code, 400)

    def test_weak_password_is_rejected(self):
        """Django's validators are configured, so they have to be applied."""
        response = self.post(new_password="abc", confirm_password="abc")
        self.assertEqual(response.status_code, 400)

    def test_rejected_request_leaves_the_old_password_intact(self):
        self.post(confirm_password="SomethingElse789")
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(OLD_PASSWORD))

    def test_invalid_token_returns_400(self):
        self.assertEqual(self.post(self.url(token="not-a-token")).status_code, 400)

    def test_malformed_uid_returns_400_instead_of_crashing(self):
        self.assertEqual(self.post(self.url(uid="!!!not-base64!!!")).status_code, 400)

    def test_token_of_another_account_is_rejected(self):
        other = create_member("other@example.com")
        foreign = default_token_generator.make_token(other)
        self.assertEqual(self.post(self.url(token=foreign)).status_code, 400)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(OLD_PASSWORD))
