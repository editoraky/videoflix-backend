"""Views for the authentication endpoints."""

from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from .emails import send_activation_email
from .serializers import RegistrationSerializer
from .utils import build_registration_response


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
