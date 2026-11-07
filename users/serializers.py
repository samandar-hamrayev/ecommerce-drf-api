from django.conf import settings
from django.contrib.auth.password_validation import validate_password
from django.core.mail import send_mail
from django.db import transaction
from rest_framework import serializers

from .models import EmailVerification, User

INVALID_CODE = "Invalid or expired code."


def _send_code(user: User, subject: str, code: str) -> None:
    send_mail(
        subject,
        f"Your code is: {code}",
        settings.DEFAULT_FROM_EMAIL,
        [user.email],
        fail_silently=False,
    )


class UserSerializer(serializers.ModelSerializer):
    """Profile of the current user; role flags are read-only."""

    class Meta:
        model = User
        fields = [
            "id",
            "email",
            "first_name",
            "last_name",
            "full_name",
            "gender",
            "avatar",
            "born_date",
            "is_staff",
            "created",
            "updated",
        ]
        read_only_fields = ["id", "email", "full_name", "is_staff", "created", "updated"]


class AdminUserSerializer(UserSerializer):
    """Used by staff to manage accounts, including activation and roles."""

    class Meta(UserSerializer.Meta):
        fields = [*UserSerializer.Meta.fields, "is_active", "is_superuser"]
        read_only_fields = ["id", "email", "full_name", "created", "updated"]

    def validate(self, attrs):
        request = self.context["request"]
        if "is_superuser" in attrs and not request.user.is_superuser:
            raise serializers.ValidationError(
                {"is_superuser": "Only superusers can grant superuser rights."}
            )
        return attrs


class PublicUserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "full_name"]


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(
        write_only=True, min_length=8, style={"input_type": "password"}
    )

    class Meta:
        model = User
        fields = ["email", "password", "first_name", "last_name"]

    def validate_email(self, value):
        value = User.objects.normalize_email(value).lower()
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError("A user with this email already exists.")
        return value

    def validate(self, attrs):
        validate_password(
            attrs["password"], user=User(**{k: v for k, v in attrs.items() if k != "password"})
        )
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        user = User.objects.create_user(**validated_data)
        verification = EmailVerification.objects.create(user=user)
        transaction.on_commit(lambda: _send_code(user, "Confirm your email", verification.code))
        return user


class ConfirmEmailSerializer(serializers.Serializer):
    email = serializers.EmailField()
    code = serializers.CharField(min_length=6, max_length=6)

    def validate(self, attrs):
        verification = (
            EmailVerification.objects.select_related("user")
            .filter(user__email__iexact=attrs["email"])
            .first()
        )
        if verification is None or not verification.matches(attrs["code"]):
            raise serializers.ValidationError(INVALID_CODE)
        attrs["verification"] = verification
        return attrs

    @transaction.atomic
    def save(self, **kwargs):
        verification = self.validated_data["verification"]
        user = verification.user
        user.is_active = True
        user.save(update_fields=["is_active"])
        verification.is_used = True
        verification.save(update_fields=["is_used"])
        return user


class ChangePasswordSerializer(serializers.Serializer):
    old_password = serializers.CharField(write_only=True)
    new_password = serializers.CharField(write_only=True, min_length=8)

    def validate_old_password(self, value):
        if not self.context["request"].user.check_password(value):
            raise serializers.ValidationError("Old password is incorrect.")
        return value

    def validate_new_password(self, value):
        validate_password(value, user=self.context["request"].user)
        return value

    def save(self, **kwargs):
        user = self.context["request"].user
        user.set_password(self.validated_data["new_password"])
        user.save(update_fields=["password"])
        return user


class ResetPasswordSerializer(serializers.Serializer):
    email = serializers.EmailField()

    def save(self, **kwargs):
        # Do not reveal whether the e-mail is registered (user enumeration).
        user = User.objects.filter(email__iexact=self.validated_data["email"]).first()
        if user is None:
            return
        verification, _ = EmailVerification.objects.get_or_create(user=user)
        verification.refresh_code()
        _send_code(user, "Password reset code", verification.code)


class ResetPasswordConfirmSerializer(ConfirmEmailSerializer):
    new_password = serializers.CharField(write_only=True, min_length=8)

    def validate(self, attrs):
        attrs = super().validate(attrs)
        validate_password(attrs["new_password"], user=attrs["verification"].user)
        return attrs

    @transaction.atomic
    def save(self, **kwargs):
        verification = self.validated_data["verification"]
        user = verification.user
        user.set_password(self.validated_data["new_password"])
        user.save(update_fields=["password"])
        verification.is_used = True
        verification.save(update_fields=["is_used"])
        return user


class LogoutSerializer(serializers.Serializer):
    refresh = serializers.CharField()
