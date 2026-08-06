"""Views for the authentication endpoints."""

from django.contrib.auth.tokens import default_token_generator
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from .emails import send_activation_email
from .serializers import RegistrationSerializer
from .utils import activate_user, build_registration_response, get_user_from_uidb64

ACTIVATION_SUCCESS = "Account successfully activated."
ACTIVATION_FAILURE = "Activation failed."


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
