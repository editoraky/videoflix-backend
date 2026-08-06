"""Outgoing emails for the authentication flow."""

from django.conf import settings
from django.contrib.auth.tokens import default_token_generator
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

ACTIVATION_PATH = "/pages/auth/activate.html"
ACTIVATION_SUBJECT = "Confirm your email"


def build_activation_link(user):
    """Return the activation URL that belongs in the email.

    The link points at the FRONTEND, not at the API, and passes uid and token as
    query parameters — ui_helper.js reads them with URLSearchParams. The page
    then calls GET /api/activate/<uid>/<token>/ itself.

    Sending the backend endpoint instead would show the reader raw JSON.
    """
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = default_token_generator.make_token(user)
    return f"{settings.FRONTEND_BASE_URL}{ACTIVATION_PATH}?uid={uid}&token={token}"


def send_activation_email(user):
    """Send the confirmation email as plain text with an HTML alternative.

    Both parts carry the same link. Clients that refuse HTML still show a
    usable message instead of an empty body.
    """
    context = {"user_name": user.email, "activation_link": build_activation_link(user)}
    message = EmailMultiAlternatives(
        subject=ACTIVATION_SUBJECT,
        body=render_to_string("emails/activation.txt", context),
        to=[user.email],
    )
    message.attach_alternative(render_to_string("emails/activation.html", context), "text/html")
    message.send()
