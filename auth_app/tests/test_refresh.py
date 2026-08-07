"""Tests for the token refresh endpoint.

Contract C-8: the refresh token comes from the cookie. video_list.js:232-237
sends no body and never looks at the response — only the new cookie matters.

Contract C-11: refresh must not require IsAuthenticated. It exists for the
moment the access token has expired; demanding a valid one would make it
reachable only when it is not needed.
"""

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import override_settings
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import AccessToken, RefreshToken

User = get_user_model()

REFRESH_URL = "/api/token/refresh/"


class RefreshTests(APITestCase):
    """Renewing a session from the refresh cookie alone."""

    def setUp(self):
        self.user = User.objects.create_user(
            username="member@example.com",
            email="member@example.com",
            password="SecurePass123",
            is_active=True,
        )
        self.refresh = RefreshToken.for_user(self.user)
        self.client.cookies[settings.AUTH_COOKIE_REFRESH] = str(self.refresh)

    def test_valid_refresh_cookie_returns_200(self):
        self.assertEqual(self.client.post(REFRESH_URL).status_code, 200)

    def test_no_request_body_is_required(self):
        self.assertEqual(self.client.post(REFRESH_URL, {}, format="json").status_code, 200)

    def test_a_new_access_cookie_is_set(self):
        response = self.client.post(REFRESH_URL)
        self.assertIn(settings.AUTH_COOKIE_ACCESS, response.cookies)
        self.assertTrue(response.cookies[settings.AUTH_COOKIE_ACCESS]["httponly"])

    def test_the_new_access_token_belongs_to_the_same_account(self):
        response = self.client.post(REFRESH_URL)
        token = AccessToken(response.cookies[settings.AUTH_COOKIE_ACCESS].value)
        self.assertEqual(str(token["user_id"]), str(self.user.pk))

    def test_refresh_cookie_is_rotated_as_well(self):
        """ROTATE_REFRESH_TOKENS is on, so a new refresh token is issued.

        Without writing it back, the browser would keep the old one — which
        BLACKLIST_AFTER_ROTATION has just invalidated. The session would then
        die at the next refresh instead of continuing.
        """
        response = self.client.post(REFRESH_URL)
        self.assertIn(settings.AUTH_COOKIE_REFRESH, response.cookies)
        self.assertNotEqual(
            response.cookies[settings.AUTH_COOKIE_REFRESH].value, str(self.refresh)
        )

    def test_the_previous_refresh_token_stops_working(self):
        """A rotated token must not survive — otherwise rotation buys nothing."""
        self.client.post(REFRESH_URL)
        self.client.cookies[settings.AUTH_COOKIE_REFRESH] = str(self.refresh)
        self.assertEqual(self.client.post(REFRESH_URL).status_code, 401)

    def test_refresh_works_without_an_access_cookie(self):
        """Contract C-11: this is the whole point of the endpoint."""
        self.assertNotIn(settings.AUTH_COOKIE_ACCESS, self.client.cookies)
        self.assertEqual(self.client.post(REFRESH_URL).status_code, 200)

    def test_missing_refresh_cookie_returns_400(self):
        """Documented: 400 when the refresh token is absent."""
        self.client.cookies.clear()
        self.assertEqual(self.client.post(REFRESH_URL).status_code, 400)

    def test_invalid_refresh_token_returns_401(self):
        """Documented: 401 for an invalid refresh token."""
        self.client.cookies[settings.AUTH_COOKIE_REFRESH] = "not-a-jwt"
        self.assertEqual(self.client.post(REFRESH_URL).status_code, 401)

    def test_blacklisted_token_returns_401(self):
        """Logging out has to end the session for good."""
        self.refresh.blacklist()
        self.assertEqual(self.client.post(REFRESH_URL).status_code, 401)

    def test_refresh_token_of_a_deleted_account_returns_401(self):
        """A deleted account must not turn into a server error.

        The token itself stays cryptographically sound, so SimpleJWT raises
        nothing — the lookup for the account does. Uncaught, that reaches the
        client as a 500 with a stack trace instead of a status code, and a
        browser left open after an account deletion is a perfectly ordinary case.
        """
        self.user.delete()
        self.assertEqual(self.client.post(REFRESH_URL).status_code, 401)

    def test_detail_matches_the_documentation(self):
        self.assertEqual(self.client.post(REFRESH_URL).data["detail"], "Token refreshed")

    @override_settings(DEBUG=True)
    def test_access_token_is_shown_while_debugging(self):
        """The API docs list an "access" field and call it demonstration material."""
        self.assertIn("access", self.client.post(REFRESH_URL).data)

    @override_settings(DEBUG=False)
    def test_access_token_is_withheld_outside_debugging(self):
        """A token in the body is a second carrier next to the HttpOnly cookie.

        Anything JavaScript can read defeats the reason for using HttpOnly at
        all, so the field is limited to a debugging setup — the same rule the
        registration response follows.
        """
        self.assertNotIn("access", self.client.post(REFRESH_URL).data)
