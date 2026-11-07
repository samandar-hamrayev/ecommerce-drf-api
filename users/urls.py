from django.urls import path
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from . import views

auth_tag = extend_schema_view(post=extend_schema(tags=["auth"]))

urlpatterns = [
    path("auth/register/", views.RegisterView.as_view(), name="register"),
    path("auth/confirm-email/", views.ConfirmEmailView.as_view(), name="confirm-email"),
    path("auth/login/", auth_tag(TokenObtainPairView).as_view(), name="login"),
    path("auth/token/refresh/", auth_tag(TokenRefreshView).as_view(), name="token-refresh"),
    path("auth/logout/", views.LogoutView.as_view(), name="logout"),
    path("auth/me/", views.MeView.as_view(), name="me"),
    path("auth/password/change/", views.ChangePasswordView.as_view(), name="password-change"),
    path("auth/password/reset/", views.ResetPasswordView.as_view(), name="password-reset"),
    path(
        "auth/password/reset/confirm/",
        views.ResetPasswordConfirmView.as_view(),
        name="password-reset-confirm",
    ),
    path("users/", views.UserListView.as_view(), name="user-list"),
    path("users/<int:pk>/", views.UserDetailView.as_view(), name="user-detail"),
]
