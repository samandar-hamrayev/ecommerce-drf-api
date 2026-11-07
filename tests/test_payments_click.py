import hashlib
from decimal import Decimal

import pytest
from django.urls import reverse

from orders.models import Order
from payments.models import Payment
from payments.providers.click import ClickError, build_sign

pytestmark = pytest.mark.django_db

SERVICE_ID = "12345"
SECRET = "click-test-secret"


@pytest.fixture(autouse=True)
def click_settings(settings):
    settings.CLICK_SERVICE_ID = SERVICE_ID
    settings.CLICK_MERCHANT_ID = "999"
    settings.CLICK_SECRET_KEY = SECRET


@pytest.fixture
def order(user, product, make_order):
    return make_order(user, (product, 1))  # total 150000.00


def signed(
    action, order_id, *, amount="150000.00", click_trans_id="2275614", prepare_id=None, **overrides
):
    params = {
        "click_trans_id": click_trans_id,
        "service_id": SERVICE_ID,
        "click_paydoc_id": "3350123",
        "merchant_trans_id": str(order_id),
        "amount": amount,
        "action": str(action),
        "error": "0",
        "error_note": "Success",
        "sign_time": "2026-11-07 12:00:00",
    }
    if action == 1:
        params["merchant_prepare_id"] = str(prepare_id)
    params.update(overrides)
    params["sign_string"] = build_sign(params, SECRET, action)
    return params


def prepare(client, params):
    return client.post(reverse("click-prepare"), params).json()  # form-encoded like Click


def complete(client, params):
    return client.post(reverse("click-complete"), params).json()


def do_prepare(client, order, **kw):
    body = prepare(client, signed(0, order.pk, **kw))
    assert body["error"] == ClickError.SUCCESS, body
    return body["merchant_prepare_id"]


class TestSignature:
    def test_build_sign_matches_documented_formula(self):
        params = {
            "click_trans_id": "1",
            "service_id": "2",
            "merchant_trans_id": "3",
            "amount": "1000.00",
            "action": "0",
            "sign_time": "2026-01-01 00:00:00",
        }
        raw = "1" + "2" + "secret" + "3" + "1000.00" + "0" + "2026-01-01 00:00:00"
        assert build_sign(params, "secret", 0) == hashlib.md5(raw.encode()).hexdigest()

        params.update(action="1", merchant_prepare_id="77")
        raw = "1" + "2" + "secret" + "3" + "77" + "1000.00" + "1" + "2026-01-01 00:00:00"
        assert build_sign(params, "secret", 1) == hashlib.md5(raw.encode()).hexdigest()

    def test_bad_signature_is_rejected(self, api_client, order):
        params = signed(0, order.pk)
        params["sign_string"] = "0" * 32
        assert prepare(api_client, params)["error"] == ClickError.SIGN_CHECK_FAILED
        assert not Payment.objects.exists()

    def test_tampered_amount_breaks_signature(self, api_client, order):
        params = signed(0, order.pk)
        params["amount"] = "1.00"
        assert prepare(api_client, params)["error"] == ClickError.SIGN_CHECK_FAILED

    def test_uppercase_signature_accepted(self, api_client, order):
        params = signed(0, order.pk)
        params["sign_string"] = params["sign_string"].upper()
        assert prepare(api_client, params)["error"] == ClickError.SUCCESS


class TestPrepare:
    def test_success_creates_payment(self, api_client, order):
        body = prepare(api_client, signed(0, order.pk))
        assert body == {
            "click_trans_id": "2275614",
            "merchant_trans_id": str(order.pk),
            "merchant_prepare_id": Payment.objects.get().pk,
            "error": 0,
            "error_note": "Success",
        }
        payment = Payment.objects.get()
        assert payment.state == Payment.State.CREATED
        assert payment.amount == Decimal("150000.00")
        order.refresh_from_db()
        assert order.status == Order.Status.PENDING

    def test_missing_field(self, api_client, order):
        params = signed(0, order.pk)
        del params["click_paydoc_id"]
        assert prepare(api_client, params)["error"] == ClickError.BAD_REQUEST

    def test_wrong_service_id(self, api_client, order):
        assert (
            prepare(api_client, signed(0, order.pk, service_id="1"))["error"]
            == ClickError.BAD_REQUEST
        )

    def test_wrong_action_for_endpoint(self, api_client, order):
        params = signed(1, order.pk, prepare_id=1)
        assert prepare(api_client, params)["error"] == ClickError.ACTION_NOT_FOUND
        assert prepare(api_client, signed(5, order.pk))["error"] == ClickError.ACTION_NOT_FOUND

    def test_unknown_order(self, api_client, order):
        assert prepare(api_client, signed(0, 999_999))["error"] == ClickError.USER_NOT_FOUND
        assert prepare(api_client, signed(0, "abc"))["error"] == ClickError.USER_NOT_FOUND

    @pytest.mark.parametrize("amount", ["149999.99", "150000.01", "0", "-1", "abc"])
    def test_amount_mismatch(self, api_client, order, amount):
        assert (
            prepare(api_client, signed(0, order.pk, amount=amount))["error"]
            == ClickError.INVALID_AMOUNT
        )

    def test_amount_format_variants_accepted(self, api_client, order):
        assert (
            prepare(api_client, signed(0, order.pk, amount="150000"))["error"] == ClickError.SUCCESS
        )

    def test_already_paid_order(self, api_client, order):
        Order.objects.filter(pk=order.pk).update(status=Order.Status.PAID)
        assert prepare(api_client, signed(0, order.pk))["error"] == ClickError.ALREADY_PAID

    def test_cancelled_order(self, api_client, order):
        Order.objects.filter(pk=order.pk).update(status=Order.Status.CANCELLED)
        assert prepare(api_client, signed(0, order.pk))["error"] == ClickError.TRANSACTION_CANCELLED

    def test_retry_is_idempotent(self, api_client, order):
        first = do_prepare(api_client, order)
        second = do_prepare(api_client, order)
        assert first == second
        assert Payment.objects.count() == 1


class TestComplete:
    def test_full_flow_marks_order_paid(self, api_client, order):
        prepare_id = do_prepare(api_client, order)
        body = complete(api_client, signed(1, order.pk, prepare_id=prepare_id))
        assert body["error"] == ClickError.SUCCESS
        assert body["merchant_confirm_id"] == prepare_id
        payment = Payment.objects.get()
        assert payment.state == Payment.State.PERFORMED
        assert payment.performed_at
        order.refresh_from_db()
        assert order.status == Order.Status.PAID
        assert order.paid_at

    def test_repeat_complete_reports_already_paid_without_side_effects(self, api_client, order):
        prepare_id = do_prepare(api_client, order)
        complete(api_client, signed(1, order.pk, prepare_id=prepare_id))
        again = complete(api_client, signed(1, order.pk, prepare_id=prepare_id))
        assert again["error"] == ClickError.ALREADY_PAID
        assert Payment.objects.get().state == Payment.State.PERFORMED

    def test_prepare_after_complete_reports_already_paid(self, api_client, order):
        prepare_id = do_prepare(api_client, order)
        complete(api_client, signed(1, order.pk, prepare_id=prepare_id))
        assert prepare(api_client, signed(0, order.pk))["error"] == ClickError.ALREADY_PAID

    def test_unknown_prepare_id(self, api_client, order):
        do_prepare(api_client, order)
        body = complete(api_client, signed(1, order.pk, prepare_id=424242))
        assert body["error"] == ClickError.TRANSACTION_NOT_FOUND

    def test_prepare_id_of_another_click_transaction(self, api_client, order):
        prepare_id = do_prepare(api_client, order)
        body = complete(
            api_client, signed(1, order.pk, prepare_id=prepare_id, click_trans_id="999")
        )
        assert body["error"] == ClickError.TRANSACTION_NOT_FOUND

    def test_amount_mismatch(self, api_client, order):
        prepare_id = do_prepare(api_client, order)
        body = complete(api_client, signed(1, order.pk, prepare_id=prepare_id, amount="100.00"))
        assert body["error"] == ClickError.INVALID_AMOUNT
        order.refresh_from_db()
        assert order.status == Order.Status.PENDING

    def test_click_side_error_cancels_transaction(self, api_client, order):
        prepare_id = do_prepare(api_client, order)
        params = signed(
            1, order.pk, prepare_id=prepare_id, error="-5017", error_note="Insufficient funds"
        )
        body = complete(api_client, params)
        assert body["error"] == ClickError.TRANSACTION_CANCELLED
        payment = Payment.objects.get()
        assert payment.state == Payment.State.CANCELLED  # persisted, not rolled back
        assert payment.reason == -5017
        order.refresh_from_db()
        assert order.status == Order.Status.PENDING
        # Any further complete for the cancelled transaction stays cancelled.
        again = complete(api_client, signed(1, order.pk, prepare_id=prepare_id))
        assert again["error"] == ClickError.TRANSACTION_CANCELLED

    def test_second_transaction_cannot_pay_twice(self, api_client, order):
        first = do_prepare(api_client, order, click_trans_id="1")
        second = do_prepare(api_client, order, click_trans_id="2")
        assert (
            complete(api_client, signed(1, order.pk, prepare_id=first, click_trans_id="1"))["error"]
            == 0
        )
        body = complete(api_client, signed(1, order.pk, prepare_id=second, click_trans_id="2"))
        assert body["error"] == ClickError.ALREADY_PAID

    def test_order_cancelled_between_prepare_and_complete(self, api_client, order):
        prepare_id = do_prepare(api_client, order)
        Order.objects.filter(pk=order.pk).update(status=Order.Status.CANCELLED)
        body = complete(api_client, signed(1, order.pk, prepare_id=prepare_id))
        assert body["error"] == ClickError.TRANSACTION_CANCELLED

    def test_unexpected_failure_returns_minus_7(self, api_client, order, monkeypatch):
        prepare_id = do_prepare(api_client, order)

        def boom(_order):
            raise RuntimeError("db down")

        monkeypatch.setattr("payments.services.mark_order_paid", boom)
        body = complete(api_client, signed(1, order.pk, prepare_id=prepare_id))
        assert body["error"] == ClickError.FAILED_TO_UPDATE
        assert Payment.objects.get().state == Payment.State.CREATED  # rolled back

    def test_callbacks_need_no_user_auth_and_ignore_session(self, user_client, order):
        # Even an authenticated client hits the same unauthenticated handler.
        assert prepare(user_client, signed(0, order.pk))["error"] == 0
