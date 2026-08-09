"""Authentication classes for the API."""

from django.conf import settings
from rest_framework.exceptions import AuthenticationFailed
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

    An unusable cookie yields None rather than an exception. DRF runs the
    authentication class before it consults the permissions, so raising here
    would end the request no matter which endpoint it was aimed at — including
    login, refresh and logout, the very endpoints someone needs once their
    access token has expired. An access token lives thirty minutes while its
    cookie stays in the browser far longer, so a stale cookie is the normal
    case, not an edge case.

    Returning None leaves the decision where it belongs. On a protected
    endpoint the request counts as anonymous and IsAuthenticated answers 401 —
    the code the HLS endpoints require (contract C-14). On a public endpoint the
    view simply runs.
    """

    def authenticate(self, request):
        """Return (user, token) from the cookie, or None if it cannot be used."""
        raw_token = request.COOKIES.get(settings.AUTH_COOKIE_ACCESS)
        if not raw_token:
            return None
        try:
            validated_token = self.get_validated_token(raw_token)
            return self.get_user(validated_token), validated_token
        except AuthenticationFailed:
            return None
