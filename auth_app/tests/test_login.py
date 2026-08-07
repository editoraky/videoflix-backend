"""Tests for the login endpoint.

Contract C-1: tokens travel exclusively in HttpOnly cookies. The response body
shown in the API documentation is explicitly labelled as demonstration material
— the frontend reads nothing from it and relies on the cookies being sent back
automatically because every request uses credentials: 'include'.
"""

from django.conf import settings
from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APITestCase

User = get_user_model()

LOGIN_URL = "/api/login/"
PASSWORD = "SecurePass123"


def create_active_user(email="member@example.com"):
    """Create an activated account, the state a real login starts from."""
    return User.objects.create_user(
        username=email, email=email, password=PASSWORD, is_active=True
    )


class LoginSuccessTests(APITestCase):
    """What a correct login has to deliver."""

    def setUp(self):
        self.user = create_active_user()
        self.response = self.client.post(
            LOGIN_URL, {"email": self.user.email, "password": PASSWORD}, format="json"
        )

    def test_valid_credentials_return_200(self):
        self.assertEqual(self.response.status_code, status.HTTP_200_OK)

    def test_endpoint_is_reachable_without_authentication(self):
        """DEFAULT_PERMISSION_CLASSES is IsAuthenticated — this view must opt out."""
        self.assertNotIn(self.response.status_code, (401, 403))

    def test_both_auth_cookies_are_set(self):
        self.assertIn(settings.AUTH_COOKIE_ACCESS, self.response.cookies)
        self.assertIn(settings.AUTH_COOKIE_REFRESH, self.response.cookies)

    def test_both_cookies_are_httponly(self):
        """A token readable from JavaScript is one XSS away from being stolen."""
        for name in (settings.AUTH_COOKIE_ACCESS, settings.AUTH_COOKIE_REFRESH):
            with self.subTest(cookie=name):
                self.assertTrue(self.response.cookies[name]["httponly"])

    def test_cookies_are_scoped_to_the_whole_site(self):
        """HLS segments live under /api/video/..., login answers from /api/login/."""
        for name in (settings.AUTH_COOKIE_ACCESS, settings.AUTH_COOKIE_REFRESH):
            with self.subTest(cookie=name):
                self.assertEqual(self.response.cookies[name]["path"], "/")

    def test_response_body_matches_the_documentation(self):
        """Documented: {"detail": "Login successful", "user": {"id": .., "username": ..}}."""
        self.assertEqual(self.response.data["detail"], "Login successful")
        self.assertEqual(sorted(self.response.data["user"].keys()), ["id", "username"])

    def test_username_in_the_body_is_the_email(self):
        """Registration stores the address in both fields, so this matches the docs."""
        self.assertEqual(self.response.data["user"]["username"], "member@example.com")

    def test_no_token_appears_in_the_body(self):
        """Contract C-1: the body must never be a second way to authenticate."""
        body = str(self.response.data)
        self.assertNotIn("access", body)
        self.assertNotIn("refresh", body)

    def test_no_password_leaks_into_the_body(self):
        self.assertNotIn(PASSWORD, str(self.response.data))


class LoginRejectionTests(APITestCase):
    """What has to be refused — with 401 and nothing revealed."""

    GENERIC = "Please check your input and try again."

    def setUp(self):
        self.user = create_active_user()

    def post(self, **overrides):
        data = {"email": self.user.email, "password": PASSWORD}
        data.update(overrides)
        return self.client.post(LOGIN_URL, data, format="json")

    def test_wrong_password_returns_401(self):
        """Contract C-13, confirmed by the mentor: login failures answer 401."""
        self.assertEqual(self.post(password="WrongPass123").status_code, 401)

    def test_unknown_email_returns_401(self):
        self.assertEqual(self.post(email="nobody@example.com").status_code, 401)

    def test_inactive_account_returns_401(self):
        """Checklist US 1: the account must be unlocked before the first login."""
        self.user.is_active = False
        self.user.save(update_fields=["is_active"])
        self.assertEqual(self.post().status_code, 401)

    def test_no_cookies_are_set_on_failure(self):
        response = self.post(password="WrongPass123")
        self.assertNotIn(settings.AUTH_COOKIE_ACCESS, response.cookies)
        self.assertNotIn(settings.AUTH_COOKIE_REFRESH, response.cookies)

    def test_every_rejection_looks_identical(self):
        """Checklist US 2 forbids revealing whether an address exists.

        Wrong password, unknown address and locked account must be
        indistinguishable — otherwise the login form becomes a lookup service
        for which addresses hold an account.
        """
        self.user.is_active = False
        self.user.save(update_fields=["is_active"])
        locked = self.post()
        self.user.is_active = True
        self.user.save(update_fields=["is_active"])

        cases = {
            "wrong password": self.post(password="WrongPass123"),
            "unknown email": self.post(email="nobody@example.com"),
            "locked account": locked,
        }
        for label, response in cases.items():
            with self.subTest(case=label):
                self.assertEqual(response.status_code, 401)
                self.assertIn(self.GENERIC, str(response.data))

    def test_message_never_mentions_the_address(self):
        response = self.post(email="probe@example.com")
        self.assertNotIn("probe@example.com", str(response.data))
