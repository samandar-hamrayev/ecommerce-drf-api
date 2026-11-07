import threading
from decimal import Decimal
from unittest import mock

import pytest
from django.db import connection, connections
from django.urls import reverse

from carts.models import CartItem
from orders.models import Order, OrderItem
from orders.services import OrderError, create_order_from_cart
from products.models import Product

pytestmark = pytest.mark.django_db

CHECKOUT = {"shipping_address": "Tashkent, Amir Temur 1", "phone": "+998901234567"}


def test_checkout_creates_order_decrements_stock_and_clears_cart(
    user_client, user, product, make_product, fill_cart
):
    sale = make_product(name="On sale", price=Decimal("199.99"), discount=15, stock=3)
    fill_cart(user, (product, 2), (sale, 3))

    response = user_client.post(reverse("order-list"), CHECKOUT, format="json")

    assert response.status_code == 201, response.json()
    body = response.json()
    assert body["status"] == "pending"
    # 2 * 150000.00 + 3 * 169.99 (discounted snapshot)
    assert body["total_amount"] == "300509.97"
    lines = {i["product_name"]: i for i in body["items"]}
    assert lines["On sale"]["unit_price"] == "169.99"
    assert lines["On sale"]["line_total"] == "509.97"
    product.refresh_from_db()
    sale.refresh_from_db()
    assert (product.stock, sale.stock) == (3, 0)
    assert not CartItem.objects.filter(cart__user=user).exists()


def test_price_snapshot_is_not_affected_by_later_price_changes(
    user_client, user, product, fill_cart
):
    fill_cart(user, (product, 1))
    order_id = user_client.post(reverse("order-list"), CHECKOUT, format="json").json()["id"]
    Product.objects.filter(pk=product.pk).update(price=Decimal("1.00"), name="Renamed")
    detail = user_client.get(reverse("order-detail", args=[order_id])).json()
    assert detail["items"][0]["unit_price"] == "150000.00"
    assert detail["items"][0]["product_name"] == "Phone X"
    assert detail["total_amount"] == "150000.00"


def test_empty_cart_cannot_checkout(user_client):
    response = user_client.post(reverse("order-list"), CHECKOUT, format="json")
    assert response.status_code == 400
    assert "cart" in response.json()


def test_checkout_requires_address(user_client, user, product, fill_cart):
    fill_cart(user, (product, 1))
    assert user_client.post(reverse("order-list"), {}, format="json").status_code == 400
    assert not Order.objects.exists()


def test_insufficient_stock_rolls_back_everything(
    user_client, user, product, make_product, fill_cart
):
    scarce = make_product(name="Scarce", stock=1)
    fill_cart(user, (product, 2), (scarce, 1))
    Product.objects.filter(pk=scarce.pk).update(stock=0)  # someone bought it meanwhile

    response = user_client.post(reverse("order-list"), CHECKOUT, format="json")

    assert response.status_code == 400
    assert "Scarce" in str(response.json())
    assert not Order.objects.exists()
    product.refresh_from_db()
    assert product.stock == 5  # untouched
    assert CartItem.objects.filter(cart__user=user).count() == 2


def test_failure_mid_checkout_is_atomic(user, product, fill_cart):
    fill_cart(user, (product, 2))
    with (
        mock.patch.object(OrderItem.objects, "bulk_create", side_effect=RuntimeError("boom")),
        pytest.raises(RuntimeError),
    ):
        create_order_from_cart(user, shipping_address="x")
    product.refresh_from_db()
    assert product.stock == 5
    assert not Order.objects.exists()
    assert CartItem.objects.filter(cart__user=user).exists()


def test_inactive_product_blocks_checkout(user, product, fill_cart):
    fill_cart(user, (product, 1))
    Product.objects.filter(pk=product.pk).update(is_active=False)
    with pytest.raises(OrderError):
        create_order_from_cart(user, shipping_address="x")


def test_checkout_only_uses_the_callers_cart(client_for, user, other_user, product, fill_cart):
    fill_cart(other_user, (product, 2))
    response = client_for(user).post(reverse("order-list"), CHECKOUT, format="json")
    assert response.status_code == 400  # user's own cart is empty
    assert CartItem.objects.filter(cart__user=other_user).count() == 1
    product.refresh_from_db()
    assert product.stock == 5


def test_orders_are_private(client_for, user, other_user, staff_client, product, make_order):
    order = make_order(other_user, (product, 1))
    assert client_for(user).get(reverse("order-detail", args=[order.pk])).status_code == 404
    assert client_for(user).get(reverse("order-list")).json()["count"] == 0
    assert staff_client.get(reverse("order-detail", args=[order.pk])).status_code == 200


def test_customer_can_cancel_pending_order_and_stock_is_restored(
    user_client, user, product, make_order
):
    order = make_order(user, (product, 2))
    product.refresh_from_db()
    assert product.stock == 3
    response = user_client.post(reverse("order-cancel", args=[order.pk]))
    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"
    product.refresh_from_db()
    assert product.stock == 5
    # cancelling twice is rejected by the state machine
    assert user_client.post(reverse("order-cancel", args=[order.pk])).status_code == 400


def test_customer_cannot_cancel_paid_order(user_client, user, product, make_order):
    order = make_order(user, (product, 1), status=Order.Status.PAID)
    assert user_client.post(reverse("order-cancel", args=[order.pk])).status_code == 400


def test_status_changes_are_staff_only_and_follow_state_machine(
    user_client, staff_client, user, product, make_order
):
    order = make_order(user, (product, 1), status=Order.Status.PAID)
    url = reverse("order-set-status", args=[order.pk])
    assert user_client.post(url, {"status": "shipped"}, format="json").status_code == 403
    assert staff_client.post(url, {"status": "delivered"}, format="json").status_code == 400
    assert staff_client.post(url, {"status": "shipped"}, format="json").status_code == 200
    response = staff_client.post(url, {"status": "delivered"}, format="json")
    assert response.status_code == 200
    assert response.json()["delivered_at"]
    assert staff_client.post(url, {"status": "cancelled"}, format="json").status_code == 400


def test_orders_cannot_be_edited_or_deleted_via_api(user_client, user, product, make_order):
    order = make_order(user, (product, 1))
    url = reverse("order-detail", args=[order.pk])
    assert user_client.patch(url, {"total_amount": "1.00"}, format="json").status_code == 405
    assert user_client.delete(url).status_code == 405


def test_order_list_query_count_is_constant(
    user_client, user, make_product, make_order, django_assert_max_num_queries
):
    for _ in range(5):
        make_order(user, (make_product(), 1), (make_product(), 2))
    with django_assert_max_num_queries(3):
        response = user_client.get(reverse("order-list"))
    assert response.json()["count"] == 5


@pytest.mark.django_db(transaction=True)
@pytest.mark.skipif(connection.vendor != "postgresql", reason="needs row-level locks (PostgreSQL)")
def test_concurrent_checkouts_never_oversell(user, other_user, make_product, fill_cart):
    last_one = make_product(name="Last one", stock=1)
    fill_cart(user, (last_one, 1))
    fill_cart(other_user, (last_one, 1))
    barrier = threading.Barrier(2)
    outcomes = []

    def checkout(u):
        try:
            barrier.wait()
            create_order_from_cart(u, shipping_address="x")
            outcomes.append("ok")
        except OrderError:
            outcomes.append("rejected")
        finally:
            connections.close_all()

    threads = [threading.Thread(target=checkout, args=(u,)) for u in (user, other_user)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert sorted(outcomes) == ["ok", "rejected"]
    last_one.refresh_from_db()
    assert last_one.stock == 0
    assert Order.objects.count() == 1
