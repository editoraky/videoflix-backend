"""Helper functions for the authentication endpoints."""

from django.contrib.auth.tokens import default_token_generator


def build_registration_response(user):
    """Return the response body documented for POST /api/register/.

    The activation token is included because the API documentation lists it.
    It is explicitly labelled there as demonstration material — the frontend
    never reads it and relies on the emailed link instead.
    """
    return {
        "user": {"id": user.id, "email": user.email},
        "token": default_token_generator.make_token(user),
    }
