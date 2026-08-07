"""Helper functions for the authentication endpoints."""

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.utils.encoding import force_str
from django.utils.http import urlsafe_base64_decode
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken

User = get_user_model()


def get_user_from_uidb64(uidb64):
    """Return the account behind a base64-encoded primary key, or None.

    The value comes straight from a URL, so it can be anything: hand-edited,
    truncated by a mail client, or pointing at a deleted account. Every one of
    those has to end in a 400, never in a 500.
    """
    try:
        return User.objects.get(pk=force_str(urlsafe_base64_decode(uidb64)))
    except (TypeError, ValueError, OverflowError, User.DoesNotExist):
        return None


def activate_user(user):
    """Unlock the account after a valid activation link."""
    user.is_active = True
    user.save(update_fields=["is_active"])


def set_auth_cookies(response, access_token, refresh_token):
    """Attach both JWTs as HttpOnly cookies and return the response.

    Contract C-1: the frontend never reads a token from a body. Every request
    uses credentials: 'include' and depends on these cookies coming back.

    httponly keeps JavaScript out, so an XSS cannot lift the session.
    secure follows DEBUG because a Secure cookie is dropped over plain HTTP,
    which is what local development runs on.
    samesite="Lax" works as long as frontend and backend share a host — see
    FALLSTRICKE F-26 on why localhost and 127.0.0.1 must not be mixed.
    """
    for name, token in (
        (settings.AUTH_COOKIE_ACCESS, access_token),
        (settings.AUTH_COOKIE_REFRESH, refresh_token),
    ):
        response.set_cookie(
            key=name,
            value=str(token),
            httponly=True,
            secure=not settings.DEBUG,
            samesite="Lax",
            path="/",
        )
    return response


def delete_auth_cookies(response):
    """Clear both auth cookies and return the response.

    The path has to match the one used when setting them, otherwise the browser
    keeps the original cookie and only drops a second, differently scoped one.
    """
    for name in (settings.AUTH_COOKIE_ACCESS, settings.AUTH_COOKIE_REFRESH):
        response.delete_cookie(key=name, path="/", samesite="Lax")
    return response


def blacklist_refresh_token(raw_token):
    """Invalidate a refresh token; return False if it was unusable anyway.

    Failure is not worth reporting to the caller: an expired or malformed token
    grants nothing, and the point of logging out is already achieved by clearing
    the cookies.
    """
    try:
        RefreshToken(raw_token).blacklist()
        return True
    except TokenError:
        return False


def rotate_refresh_token(raw_token):
    """Exchange a refresh token for a fresh pair, retiring the old one.

    Raises TokenError if the token is malformed, expired or blacklisted, which
    the caller turns into 401. A deleted account raises it too: the token stays
    cryptographically sound, so only the lookup notices, and letting
    DoesNotExist escape would answer a routine case with a 500.
    """
    old = RefreshToken(raw_token)
    old.blacklist()
    try:
        user = User.objects.get(pk=old["user_id"])
    except User.DoesNotExist:
        raise TokenError("The account behind this token no longer exists")
    new = RefreshToken.for_user(user)
    return {"access": new.access_token, "refresh": new}


def build_refresh_response_body(access_token):
    """Return the body documented for POST /api/token/refresh/.

    The API documentation lists an "access" field and labels it as material for
    demonstration; the frontend ignores the body entirely. Exposing a token
    there would hand JavaScript a copy of what HttpOnly is meant to keep away
    from it, so the field is limited to a debugging setup — the same rule the
    registration response follows.
    """
    body = {"detail": "Token refreshed"}
    if settings.DEBUG:
        body["access"] = str(access_token)
    return body


def build_login_response_body(user):
    """Return the body documented for POST /api/login/."""
    return {
        "detail": "Login successful",
        "user": {"id": user.id, "username": user.username},
    }


def build_registration_response(user):
    """Return the response body documented for POST /api/register/.

    The API documentation lists an activation token and labels it as material
    for demonstration and information; the frontend never reads it and follows
    the emailed link instead.

    Handing that token to the caller would defeat the whole point of the
    activation step — whoever registers could unlock the account without ever
    reading the inbox, so the address would never be proven to belong to them.
    The field is therefore limited to a debugging setup, where the documented
    shape stays observable, and omitted anywhere DEBUG is off.
    """
    body = {"user": {"id": user.id, "email": user.email}}
    if settings.DEBUG:
        body["token"] = default_token_generator.make_token(user)
    return body
