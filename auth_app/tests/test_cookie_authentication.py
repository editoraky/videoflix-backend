"""Tests for the cookie-based JWT authentication class.

Contract C-1: the access token travels in an HttpOnly cookie, never in a header
the frontend could set. That makes the Authorization header irrelevant here —
a token presented that way has to be ignored, otherwise the cookie rule is
merely a suggestion.

The probe endpoint below exists only for these tests: without it there would be
no protected route yet to authenticate against.
"""

from django.contrib.auth import get_user_model
from django.test import override_settings
from django.urls import path
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

User = get_user_model()


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def probe(request):
    """Minimal protected endpoint used to observe the authentication result."""
    return Response({"email": request.user.email})


urlpatterns = [path("probe/", probe)]


@override_settings(ROOT_URLCONF="auth_app.tests.test_cookie_authentication")
class CookieJWTAuthenticationTests(APITestCase):
    """Which requests reach a protected endpoint, and which do not."""

    def setUp(self):
        self.user = User.objects.create_user(
            username="member@example.com",
            email="member@example.com",
            password="SecurePass123",
            is_active=True,
        )
        self.refresh = RefreshToken.for_user(self.user)
        self.access = str(self.refresh.access_token)

    def test_request_without_any_cookie_is_rejected(self):
        self.assertEqual(self.client.get("/probe/").status_code, 401)

    def test_valid_access_cookie_is_accepted(self):
        self.client.cookies["access_token"] = self.access
        self.assertEqual(self.client.get("/probe/").status_code, 200)

    def test_authenticated_request_resolves_the_right_account(self):
        self.client.cookies["access_token"] = self.access
        response = self.client.get("/probe/")
        self.assertEqual(response.data["email"], "member@example.com")

    def test_garbage_in_the_cookie_is_rejected(self):
        self.client.cookies["access_token"] = "not-a-jwt"
        self.assertEqual(self.client.get("/probe/").status_code, 401)

    def test_empty_cookie_is_rejected(self):
        self.client.cookies["access_token"] = ""
        self.assertEqual(self.client.get("/probe/").status_code, 401)

    def test_refresh_token_is_not_accepted_as_an_access_token(self):
        """SimpleJWT stamps a token_type, and the check must not be skipped.

        Both tokens sit in cookies of the same browser. Without the type check a
        refresh token — which lives far longer — would work as a session token.
        """
        self.client.cookies["access_token"] = str(self.refresh)
        self.assertEqual(self.client.get("/probe/").status_code, 401)

    def test_authorization_header_alone_does_not_authenticate(self):
        """Contract C-1: the cookie is the only accepted carrier.

        Leaving header authentication enabled would keep a second door open that
        the frontend never uses but an attacker could.
        """
        response = self.client.get("/probe/", HTTP_AUTHORIZATION=f"Bearer {self.access}")
        self.assertEqual(response.status_code, 401)

    def test_token_of_an_inactive_account_is_rejected(self):
        """Deactivating an account must end its session, not just block new logins."""
        self.user.is_active = False
        self.user.save(update_fields=["is_active"])
        self.client.cookies["access_token"] = self.access
        self.assertEqual(self.client.get("/probe/").status_code, 401)

    def test_token_of_a_deleted_account_is_rejected(self):
        self.client.cookies["access_token"] = self.access
        self.user.delete()
        self.assertEqual(self.client.get("/probe/").status_code, 401)
