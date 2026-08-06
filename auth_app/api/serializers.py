"""Serializers for authentication endpoints."""

from django.contrib.auth import get_user_model
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
