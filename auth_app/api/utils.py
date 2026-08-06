"""Helper functions for the authentication endpoints."""

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.utils.encoding import force_str
from django.utils.http import urlsafe_base64_decode

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
