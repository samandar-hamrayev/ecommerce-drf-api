import base64
from urllib.parse import parse_qs, urlparse

import pytest
from django.urls import reverse

from orders.models import Order

pytestmark = pytest.mark.django_db


@pytest.fixture
def order(user, product, make_order):
    return make_order(user, (product, 1))


@pytest.fixture
def configured(settings):
    settings.CLICK_SERVICE_ID = "111"
    settings.CLICK_MERCHANT_ID = "222"
    settings.CLICK_SECRET_KEY = "s"
    settings.PAYME_MERCHANT_ID = "m-1"
    settings.PAYME_KEY = "k"
    settings.PAYME_CHECKOUT_URL = "https://checkout.test.paycom.uz"


@pytest.mark.usefixtures("configured")
def test_click_checkout_url(user_client, order):
    response = user_client.post(
        reverse("payment-checkout"),
        {"order": order.pk, "provider": "click", "return_url": "https://shop.example.com/done"},
        format="json",
    )
    assert response.status_code == 200
    url = urlparse(response.json()["checkout_url"])
    assert url.netloc == "my.click.uz"
    query = parse_qs(url.query)
    assert query["service_id"] == ["111"]
    assert query["merchant_id"] == ["222"]
    assert query["amount"] == ["150000.00"]
    assert query["transaction_param"] == [str(order.pk)]
    assert query["return_url"] == ["https://shop.example.com/done"]


@pytest.mark.usefixtures("configured")
def test_payme_checkout_url(user_client, order):
    response = user_client.post(
        reverse("payment-checkout"), {"order": order.pk, "provider": "payme"}, format="json"
    )
    url = response.json()["checkout_url"]
    assert url.startswith("https://checkout.test.paycom.uz/")
    decoded = base64.b64decode(url.rsplit("/", 1)[1]).decode()
    assert decoded == f"m=m-1;ac.order_id={order.pk};a=15000000"


@pytest.mark.usefixtures("configured")
def test_cannot_pay_foreign_or_paid_orders(client_for, other_user, user_client, order):
    foreign = client_for(other_user).post(
        reverse("payment-checkout"), {"order": order.pk, "provider": "click"}, format="json"
    )
    assert foreign.status_code == 404
    Order.objects.filter(pk=order.pk).update(status=Order.Status.PAID)
    paid = user_client.post(
        reverse("payment-checkout"), {"order": order.pk, "provider": "click"}, format="json"
    )
    assert paid.status_code == 400


def test_unconfigured_provider(user_client, order, settings):
    settings.CLICK_SECRET_KEY = ""
    response = user_client.post(
        reverse("payment-checkout"), {"order": order.pk, "provider": "click"}, format="json"
    )
    assert response.status_code == 503


def test_unknown_provider(user_client, order):
    response = user_client.post(
        reverse("payment-checkout"), {"order": order.pk, "provider": "paypal"}, format="json"
    )
    assert response.status_code == 400
