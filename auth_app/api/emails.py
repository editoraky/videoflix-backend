"""Outgoing emails for the authentication flow.

Delivery failures never reach the caller. An SMTP server is a service outside
this application — providers throttle, credentials expire, hosts go away — and
the documented answers of these endpoints must not depend on it.

For the password reset that is not merely robustness but the contract itself:
an unknown address sends no mail and always answers 200, so a known address
answering 500 on a delivery failure would reveal which addresses hold an
account. Failures are written to the log instead, where they belong.
"""

import logging

from django.conf import settings
from django.contrib.auth.tokens import default_token_generator
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

ACTIVATION_PATH = "/pages/auth/activate.html"
ACTIVATION_SUBJECT = "Confirm your email"
RESET_PATH = "/pages/auth/confirm_password.html"
RESET_SUBJECT = "Reset your Password"

logger = logging.getLogger(__name__)


def deliver(message, purpose):
    """Send a message and report whether it went out.

    Catches every exception on purpose. Anything the mail library raises —
    refusal, timeout, broken connection — is an operational problem, not a
    reason to fail the request that triggered it.
    """
    try:
        message.send()
    except Exception as error:
        logger.warning("Could not send the %s email: %s", purpose, error)
        return False
    return True


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
    return deliver(message, "activation")


def build_reset_link(user):
    """Return the password reset URL that belongs in the email.

    Same shape as the activation link and for the same reason: the frontend
    reads uid and token from the query string and calls the API itself.
    """
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = default_token_generator.make_token(user)
    return f"{settings.FRONTEND_BASE_URL}{RESET_PATH}?uid={uid}&token={token}"


def send_password_reset_email(user):
    """Send the reset email as plain text with an HTML alternative."""
    context = {"reset_link": build_reset_link(user)}
    message = EmailMultiAlternatives(
        subject=RESET_SUBJECT,
        body=render_to_string("emails/password_reset.txt", context),
        to=[user.email],
    )
    message.attach_alternative(
        render_to_string("emails/password_reset.html", context), "text/html"
    )
    return deliver(message, "password reset")
