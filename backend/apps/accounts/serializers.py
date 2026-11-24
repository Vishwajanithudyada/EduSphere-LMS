from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers


User = get_user_model()


class RegisterSerializer(serializers.ModelSerializer):

    password = serializers.CharField(
        write_only=True,
        required=True,
        trim_whitespace=False,
        style={"input_type": "password"},
    )

    class Meta:
        model = User
        fields = (
            "id",
            "username",
            "email",
            "password",
            "first_name",
            "last_name",
            "phone_number",
        )
        read_only_fields = ("id",)

    def validate_email(self, value):
        value = value.strip().lower()

        if not value:
            raise serializers.ValidationError(
                "Email address is required."
            )

        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError(
                "An account with this email already exists."
            )

        return value

    def validate_password(self, value):
        validate_password(value)
        return value

    def create(self, validated_data):
        password = validated_data.pop("password")

        user = User(
            **validated_data,
            role=User.Role.STUDENT,
            is_staff=False,
            is_superuser=False,
            is_email_verified=False,
        )

        user.set_password(password)
        user.save()

        return user


class LogoutSerializer(serializers.Serializer):

    refresh = serializers.CharField(
        required=True,
        trim_whitespace=True,
    )