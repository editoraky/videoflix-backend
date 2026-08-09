"""Every endpoint against every state an access cookie can be in.

F-35 slipped through 268 tests because each of them checked one situation at a
time: no cookie, or a valid one. The state in between — a cookie that is present
but unusable — never appeared, and that is the state a browser is in most of the
time, since an access token lives thirty minutes while its cookie stays far
longer.

Rather than adding one test per case discovered the hard way, this file states
the two rules the system has to obey and checks them against the full grid:

  Public endpoints answer the same, whatever the access cookie contains.
  Protected endpoints answer 200 only for a usable cookie, and 401 otherwise.

A new endpoint or a new failure mode is one line here, and any regression shows
up as the combination that broke rather than as a mystery in the browser.
"""

from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import AccessToken, RefreshToken

User = get_user_model()

PASSWORD = "SecurePass123!"


def expired_token(user):
    token = AccessToken.for_user(user)
    token.set_exp(lifetime=timedelta(seconds=-60))
    return str(token)


class CookieStateMatrixTestCase(APITestCase):
    """Builds one account plus every flavour of broken access cookie."""

    def setUp(self):
        self.user = User.objects.create_user(
            username="member@example.com",
            email="member@example.com",
            password=PASSWORD,
        )
        inactive = User.objects.create_user(
            username="locked@example.com",
            email="locked@example.com",
            password=PASSWORD,
            is_active=False,
        )
        deleted = User.objects.create_user(
            username="ghost@example.com",
            email="ghost@example.com",
            password=PASSWORD,
        )
        ghost_token = str(AccessToken.for_user(deleted))
        deleted.delete()

        self.states = {
            "no cookie": None,
            "empty string": "",
            "garbage": "not-a-token-at-all",
            "expired": expired_token(self.user),
            "refresh token used as access": str(RefreshToken.for_user(self.user)),
            "token of an inactive account": str(AccessToken.for_user(inactive)),
            "token of a deleted account": ghost_token,
        }

    def apply_state(self, value):
        """Put the cookie into the requested state before sending."""
        self.client.cookies.pop(settings.AUTH_COOKIE_ACCESS, None)
        if value is not None:
            self.client.cookies[settings.AUTH_COOKIE_ACCESS] = value

    def valid_cookie(self):
        self.apply_state(str(AccessToken.for_user(self.user)))


class PublicEndpointsIgnoreTheAccessCookieTests(CookieStateMatrixTestCase):
    """Rule one: a public endpoint answers the same, whatever the cookie holds.

    The access cookie says who someone is. These endpoints do not care — they
    are how a visitor becomes someone, or stops being them. Letting the cookie
    influence them is what locked users out in F-35.
    """

    def assert_same_for_every_state(self, send):
        """Send the request in every cookie state and compare the answers."""
        self.apply_state(None)
        expected = send()
        for name, value in self.states.items():
            with self.subTest(cookie=name):
                self.apply_state(value)
                actual = send()
                self.assertEqual(
                    actual.status_code,
                    expected.status_code,
                    msg=f"cookie state '{name}' changed the status code",
                )

    def test_login_with_correct_credentials(self):
        self.assert_same_for_every_state(
            lambda: self.client.post(
                "/api/login/",
                {"email": "member@example.com", "password": PASSWORD},
                format="json",
            )
        )

    def test_login_with_a_wrong_password(self):
        self.assert_same_for_every_state(
            lambda: self.client.post(
                "/api/login/",
                {"email": "member@example.com", "password": "Wrong123!"},
                format="json",
            )
        )

    def test_password_reset(self):
        self.assert_same_for_every_state(
            lambda: self.client.post(
                "/api/password_reset/", {"email": "member@example.com"}, format="json"
            )
        )

    def test_activation_with_a_broken_link(self):
        self.assert_same_for_every_state(
            lambda: self.client.get("/api/activate/MQ/broken-token/")
        )

    def test_password_confirm_with_a_broken_link(self):
        self.assert_same_for_every_state(
            lambda: self.client.post(
                "/api/password_confirm/MQ/broken-token/",
                {"new_password": PASSWORD, "confirm_password": PASSWORD},
                format="json",
            )
        )

    def test_logout_without_a_refresh_cookie(self):
        """Contract C-11: judged by the refresh cookie, never by the access one."""
        self.assert_same_for_every_state(lambda: self.client.post("/api/logout/"))

    def test_refresh_without_a_refresh_cookie(self):
        self.assert_same_for_every_state(
            lambda: self.client.post("/api/token/refresh/")
        )


class SessionEndpointsFollowTheRefreshCookieTests(CookieStateMatrixTestCase):
    """Contract C-11 in full: with a refresh cookie both work in every state.

    These two exist for the moment the access token has expired. If any state of
    the access cookie can stop them, they cannot do the job they are there for.
    """

    def test_refresh_succeeds_in_every_access_cookie_state(self):
        for name, value in self.states.items():
            with self.subTest(cookie=name):
                self.client.cookies[settings.AUTH_COOKIE_REFRESH] = str(
                    RefreshToken.for_user(self.user)
                )
                self.apply_state(value)
                self.assertEqual(self.client.post("/api/token/refresh/").status_code, 200)

    def test_logout_succeeds_in_every_access_cookie_state(self):
        for name, value in self.states.items():
            with self.subTest(cookie=name):
                self.client.cookies[settings.AUTH_COOKIE_REFRESH] = str(
                    RefreshToken.for_user(self.user)
                )
                self.apply_state(value)
                self.assertEqual(self.client.post("/api/logout/").status_code, 200)


class ProtectedEndpointsNeedAUsableCookieTests(CookieStateMatrixTestCase):
    """Rule two: only a usable cookie opens these, everything else is 401.

    401 rather than 403 matters: the frontend refreshes on 401 and gives up on
    403, and the mentor asked for 401 explicitly (contract C-14).
    """

    PROTECTED = (
        "/api/video/",
        "/api/video/1/480p/index.m3u8",
        "/api/video/1/480p/000.ts",
    )

    def test_every_unusable_state_is_refused(self):
        for path in self.PROTECTED:
            for name, value in self.states.items():
                with self.subTest(path=path, cookie=name):
                    self.apply_state(value)
                    self.assertEqual(
                        self.client.get(path).status_code,
                        401,
                        msg=f"'{name}' should not open {path}",
                    )

    def test_a_valid_cookie_is_accepted(self):
        """The counter-check: without it the rule above could pass on a broken door."""
        self.valid_cookie()
        self.assertEqual(self.client.get("/api/video/").status_code, 200)
