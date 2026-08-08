"""Tests for the logout endpoint.

Contract C-8: the refresh token is read from the cookie, never from a body —
header.js:12-18 sends no body at all.

Contract C-11: logout must not require IsAuthenticated. It is needed precisely
when the access token has expired, and the API docs list no 401 for it.
"""

from django.conf import settings
from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken
from rest_framework_simplejwt.tokens import RefreshToken

User = get_user_model()

LOGOUT_URL = "/api/logout/"


class LogoutTests(APITestCase):
    """What signing out has to achieve — and what must not stop it."""

    def setUp(self):
        self.user = User.objects.create_user(
            username="member@example.com",
            email="member@example.com",
            password="SecurePass123",
            is_active=True,
        )
        self.refresh = RefreshToken.for_user(self.user)
        self.client.cookies[settings.AUTH_COOKIE_REFRESH] = str(self.refresh)
        self.client.cookies[settings.AUTH_COOKIE_ACCESS] = str(self.refresh.access_token)

    def cookie_is_cleared(self, response, name):
        """Django clears a cookie by sending it back empty with max-age 0."""
        return response.cookies[name].value == "" and response.cookies[name]["max-age"] == 0

    def test_logout_returns_200(self):
        self.assertEqual(self.client.post(LOGOUT_URL).status_code, 200)

    def test_no_request_body_is_required(self):
        """header.js sends nothing but the cookies."""
        self.assertEqual(self.client.post(LOGOUT_URL, {}, format="json").status_code, 200)

    def test_response_body_matches_the_documentation(self):
        response = self.client.post(LOGOUT_URL)
        self.assertEqual(
            response.data["detail"],
            "Logout successful! All tokens will be deleted. Refresh token is now invalid.",
        )

    def test_both_cookies_are_cleared(self):
        response = self.client.post(LOGOUT_URL)
        for name in (settings.AUTH_COOKIE_ACCESS, settings.AUTH_COOKIE_REFRESH):
            with self.subTest(cookie=name):
                self.assertTrue(self.cookie_is_cleared(response, name))

    def test_cleared_cookies_use_the_same_path_they_were_set_with(self):
        """A mismatching path leaves the original cookie untouched in the browser."""
        response = self.client.post(LOGOUT_URL)
        for name in (settings.AUTH_COOKIE_ACCESS, settings.AUTH_COOKIE_REFRESH):
            with self.subTest(cookie=name):
                self.assertEqual(response.cookies[name]["path"], "/")

    def test_refresh_token_lands_on_the_blacklist(self):
        """Deleting the cookie alone would leave a copied token fully usable."""
        self.assertEqual(BlacklistedToken.objects.count(), 0)
        self.client.post(LOGOUT_URL)
        self.assertEqual(BlacklistedToken.objects.count(), 1)

    def test_blacklisted_token_can_no_longer_be_refreshed(self):
        """Naming the exception keeps the test from passing on an unrelated failure."""
        self.client.post(LOGOUT_URL)
        with self.assertRaises(TokenError):
            RefreshToken(str(self.refresh)).check_blacklist()

    def test_logout_works_without_an_access_token(self):
        """Contract C-11: an expired session must still be closable.

        With IsAuthenticated this endpoint would refuse service exactly when a
        user needs it — the cookies would stay in the browser for good.
        """
        del self.client.cookies[settings.AUTH_COOKIE_ACCESS]
        self.assertEqual(self.client.post(LOGOUT_URL).status_code, 200)

    def test_missing_refresh_cookie_returns_400(self):
        """Documented: 400 when the refresh token is absent."""
        self.client.cookies.clear()
        self.assertEqual(self.client.post(LOGOUT_URL).status_code, 400)

    def test_unusable_token_still_clears_the_cookies(self):
        """A stale token must not trap the user in a half-signed-in browser.

        Blacklisting fails here, but the token is worthless anyway — refusing to
        clear the cookies would leave the frontend believing it has a session.
        """
        self.client.cookies[settings.AUTH_COOKIE_REFRESH] = "not-a-jwt"
        response = self.client.post(LOGOUT_URL)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(self.cookie_is_cleared(response, settings.AUTH_COOKIE_REFRESH))

    def test_logging_out_twice_is_not_an_error_for_the_user(self):
        """The frontend redirects to the login page regardless (header.js:19-22)."""
        self.client.post(LOGOUT_URL)
        self.client.cookies[settings.AUTH_COOKIE_REFRESH] = str(self.refresh)
        self.assertEqual(self.client.post(LOGOUT_URL).status_code, 200)
