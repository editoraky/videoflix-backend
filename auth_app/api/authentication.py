"""Authentication classes for the API."""

from django.conf import settings
from rest_framework_simplejwt.authentication import JWTAuthentication


class CookieJWTAuthentication(JWTAuthentication):
    """Reads the access token from an HttpOnly cookie instead of a header.

    The frontend has no way to send an Authorization header: it never sees the
    token. Every request carries credentials: 'include', so the browser attaches
    the cookie by itself (contract C-1).

    Registering this as the only authentication class also closes the header
    route deliberately. Leaving JWTAuthentication active alongside it would keep
    a second door open that the frontend never uses — but an attacker who got
    hold of a token could.

    Returning None for a missing cookie lets DRF answer 401 through the normal
    permission machinery. An invalid or expired token raises InvalidToken, which
    DRF also renders as 401 — the code the HLS endpoints require (contract C-14).
    """

    def authenticate(self, request):
        """Return (user, token) from the cookie, or None if there is none."""
        raw_token = request.COOKIES.get(settings.AUTH_COOKIE_ACCESS)
        if not raw_token:
            return None
        validated_token = self.get_validated_token(raw_token)
        return self.get_user(validated_token), validated_token
