import base64
from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from orders.models import Order
from payments.models import Payment
from payments.providers.payme import TRANSACTION_TIMEOUT_MS, now_ms

pytestmark = pytest.mark.django_db

KEY = "payme-test-key"
AMOUNT = 15_000_000  # 150000.00 UZS in tiyin


@pytest.fixture(autouse=True)
def payme_settings(settings):
    settings.PAYME_MERCHANT_ID = "5e730e8e0b852a417aa49ceb"
    settings.PAYME_KEY = KEY
    settings.PAYME_ACCOUNT_FIELD = "order_id"


@pytest.fixture
def order(user, product, make_order):
    return make_order(user, (product, 1))


def auth(login="Paycom", key=KEY):
    return "Basic " + base64.b64encode(f"{login}:{key}".encode()).decode()


def rpc(client, method, params, *, authorization=None, raw=None):
    kwargs = {"HTTP_AUTHORIZATION": authorization or auth()}
    body = (
        raw if raw is not None else {"jsonrpc": "2.0", "id": 7, "method": method, "params": params}
    )
    response = client.post(
        reverse("payme"),
        body,
        format=None if raw is not None else "json",
        content_type="application/json" if raw is not None else None,
        **kwargs,
    )
    assert response.status_code == 200  # JSON-RPC errors still use HTTP 200
    return response.json()


def error_code(body):
    return body["error"]["code"]


def account(order):
    return {"order_id": str(order.pk)}


def create(client, order, tx_id="tx-1", amount=AMOUNT, time=None):
    return rpc(
        client,
        "CreateTransaction",
        {"id": tx_id, "time": time or now_ms(), "amount": amount, "account": account(order)},
    )


class TestProtocol:
    @pytest.mark.parametrize("header", [None, "Bearer x", "Basic !!!", "wrong"])
    def test_missing_or_malformed_auth(self, api_client, order, header):
        response = api_client.post(
            reverse("payme"),
            {"id": 1, "method": "CheckTransaction", "params": {"id": "x"}},
            format="json",
            **({"HTTP_AUTHORIZATION": header} if header else {}),
        )
        assert response.json()["error"]["code"] == -32504

    def test_wrong_key_or_login(self, api_client, order):
        assert (
            error_code(
                rpc(api_client, "CheckTransaction", {"id": "x"}, authorization=auth(key="nope"))
            )
            == -32504
        )
        assert (
            error_code(
                rpc(api_client, "CheckTransaction", {"id": "x"}, authorization=auth(login="Admin"))
            )
            == -32504
        )

    def test_parse_error(self, api_client):
        assert error_code(rpc(api_client, "", {}, raw="{not json")) == -32700

    def test_invalid_request_and_unknown_method(self, api_client):
        assert error_code(rpc(api_client, "", {}, raw='{"id": 1, "method": "X"}')) == -32600
        body = rpc(api_client, "ChangeTheWorld", {})
        assert error_code(body) == -32601
        assert body["id"] == 7

    def test_wrong_param_types(self, api_client, order):
        body = rpc(
            api_client, "CheckPerformTransaction", {"amount": "15000000", "account": account(order)}
        )
        assert error_code(body) == -32600

    def test_error_messages_are_localised(self, api_client, order):
        body = rpc(api_client, "CheckTransaction", {"id": "missing"})
        assert set(body["error"]["message"]) == {"ru", "uz", "en"}


class TestCheckPerform:
    def test_allow(self, api_client, order):
        body = rpc(
            api_client, "CheckPerformTransaction", {"amount": AMOUNT, "account": account(order)}
        )
        assert body == {"jsonrpc": "2.0", "id": 7, "result": {"allow": True}}

    def test_wrong_amount(self, api_client, order):
        body = rpc(
            api_client, "CheckPerformTransaction", {"amount": AMOUNT - 1, "account": account(order)}
        )
        assert error_code(body) == -31001

    @pytest.mark.parametrize("acc", [{}, {"order_id": "abc"}, {"order_id": "999999"}])
    def test_unknown_order(self, api_client, order, acc):
        body = rpc(api_client, "CheckPerformTransaction", {"amount": AMOUNT, "account": acc})
        assert error_code(body) == -31050
        assert body["error"]["data"] == "order_id"

    def test_order_not_payable(self, api_client, order):
        Order.objects.filter(pk=order.pk).update(status=Order.Status.PAID)
        body = rpc(
            api_client, "CheckPerformTransaction", {"amount": AMOUNT, "account": account(order)}
        )
        assert error_code(body) == -31051


class TestCreate:
    def test_create_and_idempotent_repeat(self, api_client, order):
        first = create(api_client, order)["result"]
        assert first["state"] == 1
        again = create(api_client, order)["result"]
        assert again == first
        assert Payment.objects.count() == 1

    def test_second_transaction_for_same_order_is_rejected(self, api_client, order):
        create(api_client, order, tx_id="tx-1")
        assert error_code(create(api_client, order, tx_id="tx-2")) == -31051

    def test_validates_amount_and_order(self, api_client, order):
        assert error_code(create(api_client, order, amount=1)) == -31001

    def test_stale_payme_time_is_rejected(self, api_client, order):
        stale = now_ms() - TRANSACTION_TIMEOUT_MS - 1000
        assert error_code(create(api_client, order, time=stale)) == -31008

    def test_expired_transaction_is_cancelled_with_reason_4(self, api_client, order):
        create(api_client, order)
        Payment.objects.update(created_at=timezone.now() - timedelta(hours=13))
        assert error_code(create(api_client, order)) == -31008
        payment = Payment.objects.get()
        assert (payment.state, payment.reason) == (-1, 4)

    def test_create_on_non_created_state(self, api_client, order):
        create(api_client, order)
        rpc(api_client, "CancelTransaction", {"id": "tx-1", "reason": 3})
        assert error_code(create(api_client, order)) == -31008


class TestPerform:
    def test_perform_marks_order_paid_and_is_idempotent(self, api_client, order):
        create(api_client, order)
        first = rpc(api_client, "PerformTransaction", {"id": "tx-1"})["result"]
        assert first["state"] == 2
        assert first["perform_time"] > 0
        order.refresh_from_db()
        assert order.status == Order.Status.PAID
        assert rpc(api_client, "PerformTransaction", {"id": "tx-1"})["result"] == first

    def test_unknown_transaction(self, api_client):
        assert error_code(rpc(api_client, "PerformTransaction", {"id": "nope"})) == -31003

    def test_expired(self, api_client, order):
        create(api_client, order)
        Payment.objects.update(created_at=timezone.now() - timedelta(hours=13))
        assert error_code(rpc(api_client, "PerformTransaction", {"id": "tx-1"})) == -31008
        assert Payment.objects.get().state == -1
        order.refresh_from_db()
        assert order.status == Order.Status.PENDING

    def test_cancelled_transaction_cannot_be_performed(self, api_client, order):
        create(api_client, order)
        rpc(api_client, "CancelTransaction", {"id": "tx-1", "reason": 3})
        assert error_code(rpc(api_client, "PerformTransaction", {"id": "tx-1"})) == -31008

    def test_order_cancelled_by_customer_meanwhile(self, api_client, order):
        create(api_client, order)
        Order.objects.filter(pk=order.pk).update(status=Order.Status.CANCELLED)
        assert error_code(rpc(api_client, "PerformTransaction", {"id": "tx-1"})) == -31008


class TestCancel:
    def test_cancel_created(self, api_client, order):
        create(api_client, order)
        result = rpc(api_client, "CancelTransaction", {"id": "tx-1", "reason": 3})["result"]
        assert result["state"] == -1
        assert result["cancel_time"] > 0
        order.refresh_from_db()
        assert order.status == Order.Status.PENDING  # customer may retry payment
        # repeat returns the same result
        assert rpc(api_client, "CancelTransaction", {"id": "tx-1", "reason": 3})["result"] == result

    def test_cancel_performed_refunds_and_restocks(self, api_client, order, product):
        create(api_client, order)
        rpc(api_client, "PerformTransaction", {"id": "tx-1"})
        product.refresh_from_db()
        stock_before = product.stock
        result = rpc(api_client, "CancelTransaction", {"id": "tx-1", "reason": 5})["result"]
        assert result["state"] == -2
        order.refresh_from_db()
        assert order.status == Order.Status.CANCELLED
        product.refresh_from_db()
        assert product.stock == stock_before + 1

    def test_cannot_cancel_after_shipping(self, api_client, order):
        create(api_client, order)
        rpc(api_client, "PerformTransaction", {"id": "tx-1"})
        Order.objects.filter(pk=order.pk).update(status=Order.Status.SHIPPED)
        assert (
            error_code(rpc(api_client, "CancelTransaction", {"id": "tx-1", "reason": 5})) == -31007
        )
        assert Payment.objects.get().state == 2

    def test_cancel_unknown(self, api_client):
        assert error_code(rpc(api_client, "CancelTransaction", {"id": "x", "reason": 1})) == -31003


class TestCheckAndStatement:
    def test_check_transaction_reflects_lifecycle(self, api_client, order):
        create(api_client, order)
        created = rpc(api_client, "CheckTransaction", {"id": "tx-1"})["result"]
        assert (
            created["state"],
            created["perform_time"],
            created["cancel_time"],
            created["reason"],
        ) == (1, 0, 0, None)
        rpc(api_client, "PerformTransaction", {"id": "tx-1"})
        rpc(api_client, "CancelTransaction", {"id": "tx-1", "reason": 5})
        final = rpc(api_client, "CheckTransaction", {"id": "tx-1"})["result"]
        assert final["state"] == -2
        assert final["reason"] == 5
        assert final["create_time"] == created["create_time"]
        assert final["perform_time"] > 0
        assert final["cancel_time"] > 0

    def test_get_statement_filters_by_payme_time(
        self, api_client, order, user, make_product, make_order
    ):
        t0 = now_ms()
        create(api_client, order, tx_id="in-range", time=t0)
        other = make_order(user, (make_product(price="10.00"), 1))
        create(api_client, other, tx_id="too-late", amount=1000, time=t0 + 10_000)
        body = rpc(api_client, "GetStatement", {"from": t0 - 1, "to": t0 + 1})
        txs = body["result"]["transactions"]
        assert [t["id"] for t in txs] == ["in-range"]
        assert txs[0]["amount"] == AMOUNT
        assert txs[0]["account"] == {"order_id": str(order.pk)}
        assert txs[0]["time"] == t0
