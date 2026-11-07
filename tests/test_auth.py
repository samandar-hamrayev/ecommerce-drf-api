import pytest
from django.core import mail
from django.urls import reverse

from users.models import EmailVerification, User

from .conftest import PASSWORD

pytestmark = pytest.mark.django_db


def _register(client, email="new@example.com"):
    return client.post(
        reverse("register"),
        {"email": email, "password": PASSWORD, "first_name": "New", "last_name": "User"},
        format="json",
    )


def test_register_creates_inactive_user_and_sends_code(
    api_client, django_capture_on_commit_callbacks
):
    with django_capture_on_commit_callbacks(execute=True):
        response = _register(api_client)
    assert response.status_code == 201
    user = User.objects.get(email="new@example.com")
    assert not user.is_active
    assert len(mail.outbox) == 1
    assert user.email_verification.code in mail.outbox[0].body


def test_register_rejects_duplicate_and_weak_password(api_client, user):
    assert _register(api_client, email=user.email).status_code == 400
    weak = api_client.post(
        reverse("register"), {"email": "x@example.com", "password": "12345678"}, format="json"
    )
    assert weak.status_code == 400


def test_confirm_email_activates_and_returns_tokens(api_client):
    _register(api_client)
    verification = EmailVerification.objects.get(user__email="new@example.com")
    bad = api_client.post(
        reverse("confirm-email"), {"email": "new@example.com", "code": "000000"}, format="json"
    )
    assert bad.status_code == 400
    response = api_client.post(
        reverse("confirm-email"),
        {"email": "new@example.com", "code": verification.code},
        format="json",
    )
    assert response.status_code == 200
    assert {"access", "refresh"} <= response.json().keys()
    assert User.objects.get(email="new@example.com").is_active
    # A code is single-use.
    again = api_client.post(
        reverse("confirm-email"),
        {"email": "new@example.com", "code": verification.code},
        format="json",
    )
    assert again.status_code == 400


def test_login_refresh_logout_flow(api_client, user):
    login = api_client.post(
        reverse("login"), {"email": user.email, "password": PASSWORD}, format="json"
    )
    assert login.status_code == 200
    tokens = login.json()

    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")
    me = api_client.get(reverse("me"))
    assert me.status_code == 200
    assert me.json()["email"] == user.email

    logout = api_client.post(reverse("logout"), {"refresh": tokens["refresh"]}, format="json")
    assert logout.status_code == 205
    refresh = api_client.post(
        reverse("token-refresh"), {"refresh": tokens["refresh"]}, format="json"
    )
    assert refresh.status_code == 401  # blacklisted


def test_inactive_user_cannot_login(api_client, db):
    User.objects.create_user(email="inactive@example.com", password=PASSWORD)
    response = api_client.post(
        reverse("login"), {"email": "inactive@example.com", "password": PASSWORD}, format="json"
    )
    assert response.status_code == 401


def test_user_cannot_escalate_own_role(user_client, user):
    response = user_client.patch(
        reverse("me"), {"is_staff": True, "first_name": "Al"}, format="json"
    )
    assert response.status_code == 200
    user.refresh_from_db()
    assert user.first_name == "Al"
    assert not user.is_staff


def test_user_admin_endpoints_are_staff_only(user_client, staff_client, other_user):
    assert user_client.get(reverse("user-list")).status_code == 403
    url = reverse("user-detail", args=[other_user.pk])
    assert user_client.patch(url, {"is_staff": True}, format="json").status_code == 403
    assert staff_client.patch(url, {"is_staff": True}, format="json").status_code == 200
    other_user.refresh_from_db()
    assert other_user.is_staff
    # Staff (non-superuser) cannot hand out superuser rights.
    assert staff_client.patch(url, {"is_superuser": True}, format="json").status_code == 400


def test_change_password(user_client, user):
    wrong = user_client.post(
        reverse("password-change"),
        {"old_password": "nope", "new_password": "purple-monkey-dishwasher"},
        format="json",
    )
    assert wrong.status_code == 400
    ok = user_client.post(
        reverse("password-change"),
        {"old_password": PASSWORD, "new_password": "purple-monkey-dishwasher"},
        format="json",
    )
    assert ok.status_code == 204
    user.refresh_from_db()
    assert user.check_password("purple-monkey-dishwasher")


def test_password_reset_does_not_leak_accounts(api_client, user):
    unknown = api_client.post(
        reverse("password-reset"), {"email": "ghost@example.com"}, format="json"
    )
    known = api_client.post(reverse("password-reset"), {"email": user.email}, format="json")
    assert unknown.status_code == known.status_code == 202
    assert unknown.json() == known.json()
    assert len(mail.outbox) == 1

    code = EmailVerification.objects.get(user=user).code
    confirm = api_client.post(
        reverse("password-reset-confirm"),
        {"email": user.email, "code": code, "new_password": "quiet-river-lantern"},
        format="json",
    )
    assert confirm.status_code == 204
    user.refresh_from_db()
    assert user.check_password("quiet-river-lantern")
