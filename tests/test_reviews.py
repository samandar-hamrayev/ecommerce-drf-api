import pytest
from django.urls import reverse

from orders.models import Order
from reviews.models import Review

pytestmark = pytest.mark.django_db


@pytest.fixture
def delivered(user, product, make_order):
    return make_order(user, (product, 1), status=Order.Status.DELIVERED)


def _post(client, product, rating=5, comment="Great"):
    return client.post(
        reverse("review-list"),
        {"product": product.pk, "rating": rating, "comment": comment},
        format="json",
    )


def test_reviews_are_public(api_client, user, product):
    Review.objects.create(user=user, product=product, rating=4)
    response = api_client.get(reverse("review-list"), {"product": product.pk})
    assert response.status_code == 200
    assert response.json()["count"] == 1


def test_anonymous_cannot_post(api_client, product):
    assert _post(api_client, product).status_code == 401


def test_only_buyers_of_delivered_orders_can_review(user_client, user, product, make_order):
    assert _post(user_client, product).status_code == 400
    order = make_order(user, (product, 1))  # pending, not delivered yet
    assert _post(user_client, product).status_code == 400
    Order.objects.filter(pk=order.pk).update(status=Order.Status.DELIVERED)
    response = _post(user_client, product)
    assert response.status_code == 201
    assert response.json()["user"] == user.full_name


@pytest.mark.usefixtures("delivered")
def test_one_review_per_user_and_product(user_client, product):
    assert _post(user_client, product).status_code == 201
    second = _post(user_client, product, rating=1)
    assert second.status_code == 400
    assert Review.objects.count() == 1


@pytest.mark.usefixtures("delivered")
@pytest.mark.parametrize("rating", [0, 6])
def test_rating_range(user_client, product, rating):
    assert _post(user_client, product, rating=rating).status_code == 400


@pytest.mark.usefixtures("delivered")
def test_only_author_can_edit_or_delete(user_client, client_for, other_user, product):
    review_id = _post(user_client, product).json()["id"]
    url = reverse("review-detail", args=[review_id])
    other = client_for(other_user)
    assert other.patch(url, {"rating": 1}, format="json").status_code == 403
    assert other.delete(url).status_code == 403
    assert user_client.patch(url, {"rating": 3}, format="json").json()["rating"] == 3
    assert user_client.delete(url).status_code == 204


@pytest.mark.usefixtures("delivered")
def test_review_product_is_immutable(user_client, product, make_product):
    review_id = _post(user_client, product).json()["id"]
    response = user_client.patch(
        reverse("review-detail", args=[review_id]), {"product": make_product().pk}, format="json"
    )
    assert response.status_code == 400
