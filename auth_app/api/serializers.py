"""Serializers for authentication endpoints."""

from django.contrib.auth import authenticate, get_user_model
from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers

User = get_user_model()

# Checklist US 1 and US 2 require generic messages: a specific "this email is
# already registered" would let anyone probe which addresses hold an account.
# Every rejection therefore carries this one sentence, so a taken address is
# indistinguishable from a mistyped password.
GENERIC_ERROR = "Please check your input and try again."


class RegistrationSerializer(serializers.ModelSerializer):
    """Creates an inactive account from email, password and confirmation.

    register.html submits email, password, confirmed_password and the consent
    checkbox as privacy_policy="on". The checkbox is not declared here: DRF
    ignores unknown keys, and rejecting it would break the form.

    The account starts inactive and is unlocked by the activation link
    (checklist US 1). The email is stored as the username as well, because
    backend.entrypoint.sh relies on that field and the documented login response
    returns "username": "user@example.com".
    """

    confirmed_password = serializers.CharField(write_only=True)

    class Meta:
        model = User
        fields = ("id", "email", "password", "confirmed_password")
        extra_kwargs = {"password": {"write_only": True}}

    def validate(self, attrs):
        """Reject payloads whose two password fields differ."""
        if attrs["password"] != attrs["confirmed_password"]:
            raise serializers.ValidationError(GENERIC_ERROR)
        validate_password(attrs["password"])
        return attrs

    def run_validation(self, data=serializers.empty):
        """Replace every validation error with one generic message.

        Overriding here rather than per field catches all sources at once:
        the unique constraint on email, the email format check, Django's password
        validators and the confirmation check above. Whatever went wrong, the
        response looks identical from the outside.
        """
        try:
            return super().run_validation(data)
        except serializers.ValidationError:
            raise serializers.ValidationError({"detail": [GENERIC_ERROR]})

    def create(self, validated_data):
        """Store the address in both username and email, leaving the account locked."""
        validated_data.pop("confirmed_password")
        email = validated_data["email"]
        return User.objects.create_user(
            username=email,
            email=email,
            password=validated_data["password"],
            is_active=False,
        )


class LoginSerializer(serializers.Serializer):
    """Turns email and password into an authenticated user, or refuses.

    login.html posts email and password. Since USERNAME_FIELD stayed "username",
    the account is looked up by address first and authenticated afterwards.

    authenticate() also enforces is_active, so a registered but unconfirmed
    account is refused here — with the same message as every other failure.
    """

    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)

    def validate(self, attrs):
        """Attach the authenticated user, or raise the one generic error.

        The error is wrapped in "detail" so login and registration answer with
        the same shape; DRF would otherwise file it under non_field_errors.
        """
        user = self._authenticate_by_email(attrs["email"], attrs["password"])
        if user is None:
            raise serializers.ValidationError({"detail": [GENERIC_ERROR]})
        attrs["user"] = user
        return attrs

    @staticmethod
    def _authenticate_by_email(email, password):
        """Return the matching active account, or None.

        The dummy hash for unknown addresses is not decoration: without it the
        answer comes back measurably faster when no account exists, and the
        login form turns into a lookup service for valid addresses.
        """
        user = User.objects.filter(email=email).first()
        if user is None:
            User().set_password(password)
            return None
        return authenticate(username=user.username, password=password)
