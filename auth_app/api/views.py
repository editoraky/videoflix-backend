"""Views for the authentication endpoints."""

from django.conf import settings
from django.contrib.auth.tokens import default_token_generator
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken

from .emails import send_activation_email, send_password_reset_email
from .serializers import (
    LoginSerializer,
    PasswordConfirmSerializer,
    PasswordResetRequestSerializer,
    RegistrationSerializer,
)
from .utils import (
    activate_user,
    blacklist_refresh_token,
    build_login_response_body,
    build_refresh_response_body,
    build_registration_response,
    delete_auth_cookies,
    find_resettable_account,
    get_user_from_uidb64,
    rotate_refresh_token,
    set_auth_cookies,
    set_new_password,
)

ACTIVATION_SUCCESS = "Account successfully activated."
ACTIVATION_FAILURE = "Activation failed."
LOGOUT_SUCCESS = (
    "Logout successful! All tokens will be deleted. Refresh token is now invalid."
)
LOGOUT_MISSING = "Refresh token missing."
REFRESH_MISSING = "Refresh token missing."
REFRESH_INVALID = "Invalid refresh token."
RESET_SENT = "An email has been sent to reset your password."
RESET_DONE = "Your Password has been successfully reset."
RESET_FAILED = "Password reset failed."


class RegistrationView(APIView):
    """POST /api/register/ — create a locked account and answer with 201.

    AllowAny is required, not optional: DEFAULT_PERMISSION_CLASSES is set to
    IsAuthenticated, so without opting out this endpoint would demand the very
    account it is meant to create.
    """

    permission_classes = [AllowAny]

    def post(self, request):
        """Validate the payload, store the account, send the link, answer 201."""
        serializer = RegistrationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        send_activation_email(user)
        return Response(build_registration_response(user), status=status.HTTP_201_CREATED)


class ActivationView(APIView):
    """GET /api/activate/<uidb64>/<token>/ — unlock the account behind the link.

    The frontend reads result.message on success and on failure
    (auth.js:263-282), so both answers carry that key.

    Activation is idempotent. Django's token hash covers pk, password,
    last_login, timestamp and email — not is_active — so unlocking the account
    leaves the token valid. A second click therefore succeeds again instead of
    telling someone with a working account that activation failed. The link
    retires on its own once the user logs in (last_login changes) or after
    PASSWORD_RESET_TIMEOUT.
    """

    permission_classes = [AllowAny]

    def get(self, request, uidb64, token):
        """Validate the link and unlock the account, or answer 400."""
        user = get_user_from_uidb64(uidb64)
        if user is None or not default_token_generator.check_token(user, token):
            return Response({"message": ACTIVATION_FAILURE}, status=status.HTTP_400_BAD_REQUEST)
        activate_user(user)
        return Response({"message": ACTIVATION_SUCCESS}, status=status.HTTP_200_OK)


class LoginView(APIView):
    """POST /api/login/ — authenticate and hand out both cookies.

    Answers 401 on every failure, whether the password was wrong, the address
    unknown or the account still locked. Telling them apart would turn the form
    into a lookup service for registered addresses (checklist US 2).
    """

    permission_classes = [AllowAny]

    def post(self, request):
        """Authenticate, issue the token pair, set the cookies, answer 200."""
        serializer = LoginSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_401_UNAUTHORIZED)
        user = serializer.validated_data["user"]
        refresh = RefreshToken.for_user(user)
        response = Response(build_login_response_body(user), status=status.HTTP_200_OK)
        return set_auth_cookies(response, refresh.access_token, refresh)


class LogoutView(APIView):
    """POST /api/logout/ — invalidate the refresh token and clear both cookies.

    AllowAny is required by contract C-11: logging out is needed precisely when
    the access token has expired. Demanding a valid one would leave the cookies
    stuck in the browser forever. What is checked instead is the refresh cookie.

    Blacklisting matters beyond deleting the cookie: a token copied out of the
    browser earlier would otherwise stay valid for its full lifetime.
    """

    permission_classes = [AllowAny]

    def post(self, request):
        """Blacklist the refresh token if usable, then clear the cookies."""
        raw_token = request.COOKIES.get(settings.AUTH_COOKIE_REFRESH)
        if not raw_token:
            return Response({"detail": LOGOUT_MISSING}, status=status.HTTP_400_BAD_REQUEST)
        blacklist_refresh_token(raw_token)
        response = Response({"detail": LOGOUT_SUCCESS}, status=status.HTTP_200_OK)
        return delete_auth_cookies(response)


class TokenRefreshView(APIView):
    """POST /api/token/refresh/ — issue a new access token from the cookie.

    AllowAny by contract C-11: this endpoint exists for the moment the access
    token has expired, so requiring a valid one would make it reachable only
    when it is not needed. The refresh cookie is what gets checked.

    ROTATE_REFRESH_TOKENS is on, which means the incoming refresh token is
    retired and replaced. The new one has to be written back into the cookie —
    otherwise the browser keeps a token that BLACKLIST_AFTER_ROTATION has just
    invalidated, and the session dies at the next refresh instead of continuing.
    """

    permission_classes = [AllowAny]

    def post(self, request):
        """Rotate the token pair and refresh both cookies."""
        raw_token = request.COOKIES.get(settings.AUTH_COOKIE_REFRESH)
        if not raw_token:
            return Response({"detail": REFRESH_MISSING}, status=status.HTTP_400_BAD_REQUEST)
        try:
            tokens = rotate_refresh_token(raw_token)
        except TokenError:
            return Response({"detail": REFRESH_INVALID}, status=status.HTTP_401_UNAUTHORIZED)
        response = Response(build_refresh_response_body(tokens["access"]), status=200)
        return set_auth_cookies(response, tokens["access"], tokens["refresh"])


class PasswordResetRequestView(APIView):
    """POST /api/password_reset/ — send a reset link, and say nothing more.

    Contract C-12 and checklist US 4: the answer is identical for every address.
    A different status, message or timing would let anyone check which addresses
    hold an account, so the lookup happens after the response text is already
    decided.
    """

    permission_classes = [AllowAny]

    def post(self, request):
        """Mail a link if the address belongs to an active account."""
        serializer = PasswordResetRequestSerializer(data=request.data)
        if serializer.is_valid():
            user = find_resettable_account(serializer.validated_data["email"])
            if user is not None:
                send_password_reset_email(user)
        return Response({"detail": RESET_SENT}, status=status.HTTP_200_OK)


class PasswordConfirmView(APIView):
    """POST /api/password_confirm/<uidb64>/<token>/ — set the new password.

    Single-use by construction: the password hash is part of the token
    signature, so changing it retires the link without any extra bookkeeping.
    """

    permission_classes = [AllowAny]

    def post(self, request, uidb64, token):
        """Validate link and payload, then replace the password."""
        user = get_user_from_uidb64(uidb64)
        if user is None or not default_token_generator.check_token(user, token):
            return Response({"detail": RESET_FAILED}, status=status.HTTP_400_BAD_REQUEST)
        serializer = PasswordConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        set_new_password(user, serializer.validated_data["new_password"])
        return Response({"detail": RESET_DONE}, status=status.HTTP_200_OK)
