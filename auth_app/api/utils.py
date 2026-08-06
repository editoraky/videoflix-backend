"""Helper functions for the authentication endpoints."""

from django.conf import settings
from django.contrib.auth.tokens import default_token_generator


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
