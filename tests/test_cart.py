import pytest
from django.urls import reverse

from carts.models import CartItem

pytestmark = pytest.mark.django_db


def test_cart_requires_auth(api_client):
    assert api_client.get(reverse("cart")).status_code == 401


def test_empty_cart_is_created_lazily(user_client):
    data = user_client.get(reverse("cart")).json()
    assert data["items"] == []
    assert data["total_price"] == "0.00"


def test_add_merge_update_remove(user_client, product, make_product):
    items_url = reverse("cart-item-list")
    first = user_client.post(items_url, {"product_id": product.pk, "quantity": 2}, format="json")
    assert first.status_code == 201
    # Adding the same product again merges quantities.
    second = user_client.post(items_url, {"product_id": product.pk, "quantity": 1}, format="json")
    assert second.status_code == 201
    assert second.json()["quantity"] == 3
    assert CartItem.objects.count() == 1

    discounted = make_product(price="200.00", discount=50)
    user_client.post(items_url, {"product_id": discounted.pk, "quantity": 1}, format="json")

    cart = user_client.get(reverse("cart")).json()
    assert cart["items_count"] == 4
    assert cart["total_price"] == "450100.00"  # 3 * 150000 + 1 * 100

    item_id = first.json()["id"]
    patched = user_client.patch(
        reverse("cart-item-detail", args=[item_id]), {"quantity": 1}, format="json"
    )
    assert patched.status_code == 200
    assert patched.json()["quantity"] == 1
    assert user_client.delete(reverse("cart-item-detail", args=[item_id])).status_code == 204

    assert user_client.delete(reverse("cart")).status_code == 204
    assert CartItem.objects.count() == 0


def test_adding_to_cart_does_not_reserve_stock(user_client, product):
    user_client.post(
        reverse("cart-item-list"), {"product_id": product.pk, "quantity": 2}, format="json"
    )
    product.refresh_from_db()
    assert product.stock == 5


@pytest.mark.parametrize("quantity", [0, -1, 6])
def test_quantity_validation(user_client, product, quantity):
    response = user_client.post(
        reverse("cart-item-list"), {"product_id": product.pk, "quantity": quantity}, format="json"
    )
    assert response.status_code == 400


def test_merged_quantity_cannot_exceed_stock(user_client, product):
    url = reverse("cart-item-list")
    assert (
        user_client.post(url, {"product_id": product.pk, "quantity": 4}, format="json").status_code
        == 201
    )
    assert (
        user_client.post(url, {"product_id": product.pk, "quantity": 2}, format="json").status_code
        == 400
    )


def test_inactive_product_cannot_be_added(user_client, make_product):
    hidden = make_product(is_active=False)
    response = user_client.post(reverse("cart-item-list"), {"product_id": hidden.pk}, format="json")
    assert response.status_code == 400


def test_users_cannot_touch_each_others_items(
    user_client, client_for, other_user, product, fill_cart
):
    cart = fill_cart(other_user, (product, 1))
    item = cart.items.get()
    url = reverse("cart-item-detail", args=[item.pk])
    assert user_client.get(url).status_code == 404
    assert user_client.patch(url, {"quantity": 2}, format="json").status_code == 404
    assert user_client.delete(url).status_code == 404
    assert user_client.get(reverse("cart-item-list")).json() == []
    assert client_for(other_user).get(url).status_code == 200
