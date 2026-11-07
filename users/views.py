from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import generics, status
from rest_framework.permissions import AllowAny, IsAdminUser, IsAuthenticated
from rest_framework.response import Response
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken

from .models import User
from .serializers import (
    AdminUserSerializer,
    ChangePasswordSerializer,
    ConfirmEmailSerializer,
    LogoutSerializer,
    RegisterSerializer,
    ResetPasswordConfirmSerializer,
    ResetPasswordSerializer,
    UserSerializer,
)


def _tokens_for(user):
    refresh = RefreshToken.for_user(user)
    return {"access": str(refresh.access_token), "refresh": str(refresh)}


@extend_schema(tags=["auth"])
class RegisterView(generics.CreateAPIView):
    permission_classes = [AllowAny]
    serializer_class = RegisterSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        return Response(
            {"detail": "Confirmation code sent to your email.", "email": user.email},
            status=status.HTTP_201_CREATED,
        )


@extend_schema(tags=["auth"])
class ConfirmEmailView(generics.GenericAPIView):
    permission_classes = [AllowAny]
    serializer_class = ConfirmEmailSerializer

    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        return Response({"detail": "Email confirmed.", **_tokens_for(user)})


@extend_schema(tags=["auth"], responses={205: None})
class LogoutView(generics.GenericAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = LogoutSerializer

    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            RefreshToken(serializer.validated_data["refresh"]).blacklist()
        except TokenError:
            return Response(
                {"detail": "Invalid or expired token."}, status=status.HTTP_400_BAD_REQUEST
            )
        return Response(status=status.HTTP_205_RESET_CONTENT)


@extend_schema(tags=["auth"])
class MeView(generics.RetrieveUpdateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = UserSerializer

    def get_object(self):
        return self.request.user


@extend_schema(tags=["auth"], responses={204: None})
class ChangePasswordView(generics.GenericAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = ChangePasswordSerializer

    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(status=status.HTTP_204_NO_CONTENT)


@extend_schema(
    tags=["auth"],
    responses={202: OpenApiResponse(description="Code sent if the account exists")},
)
class ResetPasswordView(generics.GenericAPIView):
    permission_classes = [AllowAny]
    serializer_class = ResetPasswordSerializer

    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(
            {"detail": "If the account exists, a reset code has been sent."},
            status=status.HTTP_202_ACCEPTED,
        )


@extend_schema(tags=["auth"], responses={204: None})
class ResetPasswordConfirmView(generics.GenericAPIView):
    permission_classes = [AllowAny]
    serializer_class = ResetPasswordConfirmSerializer

    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(status=status.HTTP_204_NO_CONTENT)


@extend_schema(tags=["users"])
class UserListView(generics.ListAPIView):
    queryset = User.objects.all()
    serializer_class = AdminUserSerializer
    permission_classes = [IsAdminUser]
    filterset_fields = ["is_active", "is_staff"]
    search_fields = ["email", "first_name", "last_name"]
    ordering_fields = ["created", "email"]


@extend_schema(tags=["users"])
class UserDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = User.objects.all()
    serializer_class = AdminUserSerializer
    permission_classes = [IsAdminUser]
