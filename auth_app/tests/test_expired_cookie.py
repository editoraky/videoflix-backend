"""Tests for requests that carry an unusable access cookie.

An access token lives thirty minutes; a browser keeps its cookie far longer.
Every public endpoint therefore has to expect a stale cookie on the way in.

DRF runs the authentication class before it looks at permissions. A class that
raises on a bad token ends the request there, and AllowAny never gets a say —
which locks the user out of the very endpoints that exist to get them back in.
Logout and refresh are the sharpest case: contract C-11 has them answer for the
situation where the access token has expired.

The other half of the contract has to survive that change: protected endpoints
must still answer 401, not 403 and certainly not 200.
"""

from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import AccessToken, RefreshToken

User = get_user_model()

LOGIN_URL = "/api/login/"
LOGOUT_URL = "/api/logout/"
REFRESH_URL = "/api/token/refresh/"
REGISTER_URL = "/api/register/"
PASSWORD_RESET_URL = "/api/password_reset/"
VIDEO_URL = "/api/video/"

PASSWORD = "SecurePass123!"


def expired_access_token(user):
    """Return an access token whose lifetime ran out a minute ago."""
    token = AccessToken.for_user(user)
    token.set_exp(lifetime=timedelta(seconds=-60))
    return str(token)


class StaleCookieTestCase(APITestCase):
    """One active account whose browser still holds an expired access cookie."""

    def setUp(self):
        self.user = User.objects.create_user(
            username="member@example.com",
            email="member@example.com",
            password=PASSWORD,
        )
        self.client.cookies[settings.AUTH_COOKIE_ACCESS] = expired_access_token(
            self.user
        )


class PublicEndpointsWithStaleCookieTests(StaleCookieTestCase):
    """The way back in must not be blocked by the cookie that expired."""

    def test_login_still_works(self):
        """Otherwise the only way out is clearing cookies by hand."""
        response = self.client.post(
            LOGIN_URL,
            {"email": "member@example.com", "password": PASSWORD},
            format="json",
        )
        self.assertEqual(response.status_code, 200)

    def test_login_with_a_wrong_password_reports_the_password(self):
        """The answer has to be about the credentials, not about the old token."""
        response = self.client.post(
            LOGIN_URL,
            {"email": "member@example.com", "password": "WrongPassword123!"},
            format="json",
        )
        self.assertEqual(response.status_code, 401)
        self.assertNotIn("token_not_valid", response.content.decode())

    def test_garbage_in_the_cookie_does_not_block_login(self):
        self.client.cookies[settings.AUTH_COOKIE_ACCESS] = "not-a-token-at-all"
        response = self.client.post(
            LOGIN_URL,
            {"email": "member@example.com", "password": PASSWORD},
            format="json",
        )
        self.assertEqual(response.status_code, 200)

    def test_registration_still_works(self):
        response = self.client.post(
            REGISTER_URL,
            {
                "email": "newcomer@example.com",
                "password": PASSWORD,
                "confirmed_password": PASSWORD,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201)

    def test_password_reset_still_answers_200(self):
        response = self.client.post(
            PASSWORD_RESET_URL, {"email": "member@example.com"}, format="json"
        )
        self.assertEqual(response.status_code, 200)


class SessionEndpointsWithStaleCookieTests(StaleCookieTestCase):
    """Contract C-11: these two exist for exactly this moment."""

    def setUp(self):
        super().setUp()
        self.refresh = RefreshToken.for_user(self.user)
        self.client.cookies[settings.AUTH_COOKIE_REFRESH] = str(self.refresh)

    def test_refresh_works_while_the_access_token_is_expired(self):
        """An endpoint reachable only with a valid access token would be pointless."""
        response = self.client.post(REFRESH_URL)
        self.assertEqual(response.status_code, 200)

    def test_logout_works_while_the_access_token_is_expired(self):
        """Otherwise the cookies stay in the browser for good."""
        response = self.client.post(LOGOUT_URL)
        self.assertEqual(response.status_code, 200)


class ProtectedEndpointsWithStaleCookieTests(StaleCookieTestCase):
    """The other half of the contract, unchanged."""

    def test_the_catalogue_stays_closed(self):
        self.assertEqual(self.client.get(VIDEO_URL).status_code, 401)

    def test_the_playlist_stays_closed(self):
        """Contract C-14: no valid access cookie means 401, never 403."""
        response = self.client.get("/api/video/1/480p/index.m3u8")
        self.assertEqual(response.status_code, 401)

    def test_a_segment_stays_closed(self):
        response = self.client.get("/api/video/1/480p/000.ts")
        self.assertEqual(response.status_code, 401)
