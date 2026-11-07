from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from orders.models import Order
from products.models import Category, Product, ProductField, ProductImage
from reviews.models import Review

pytestmark = pytest.mark.django_db

# 1x1 transparent GIF
GIF = (
    b"GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff!\xf9\x04\x01\x00\x00\x00\x00,"
    b"\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;"
)


def _results(response):
    return response.json()["results"]


class TestPermissions:
    def test_catalog_is_public(self, api_client, product):
        assert api_client.get(reverse("product-list")).status_code == 200
        assert api_client.get(reverse("product-detail", args=[product.pk])).status_code == 200
        assert api_client.get(reverse("category-list")).status_code == 200

    def test_anonymous_and_customers_cannot_write(self, api_client, user_client, product, category):
        payload = {"name": "Hacked", "category_id": category.pk, "price": "1.00"}
        assert api_client.post(reverse("product-list"), payload).status_code == 401
        assert user_client.post(reverse("product-list"), payload).status_code == 403
        url = reverse("product-detail", args=[product.pk])
        assert user_client.patch(url, {"price": "1.00"}).status_code == 403
        assert user_client.delete(url).status_code == 403
        assert user_client.post(reverse("category-list"), {"name": "X"}).status_code == 403

    def test_staff_crud(self, staff_client, staff, category, brand):
        created = staff_client.post(
            reverse("product-list"),
            {
                "name": "Laptop",
                "category_id": category.pk,
                "brand_id": brand.pk,
                "price": "999.99",
                "stock": 3,
                "discount": 10,
            },
            format="json",
        )
        assert created.status_code == 201, created.json()
        body = created.json()
        assert body["category"] == {"id": category.pk, "name": category.name}
        assert body["discounted_price"] == "899.99"
        product = Product.objects.get(pk=body["id"])
        assert product.created_by == staff

        url = reverse("product-detail", args=[product.pk])
        assert staff_client.patch(url, {"stock": 7}, format="json").json()["stock"] == 7
        assert staff_client.delete(url).status_code == 204
        assert not Product.objects.filter(pk=product.pk).exists()

    def test_category_with_products_cannot_be_deleted(self, staff_client, product):
        # PROTECT FK: we never silently delete products together with their category.
        response = staff_client.delete(reverse("category-detail", args=[product.category_id]))
        assert response.status_code == 409
        assert Category.objects.filter(pk=product.category_id).exists()


class TestValidation:
    @pytest.mark.parametrize(
        ("field", "value"), [("price", "0"), ("price", "-5"), ("discount", 95), ("stock", -1)]
    )
    def test_rejects_invalid_values(self, staff_client, category, field, value):
        payload = {"name": "Bad", "category_id": category.pk, "price": "10.00", field: value}
        response = staff_client.post(reverse("product-list"), payload, format="json")
        assert response.status_code == 400
        assert field in response.json()

    def test_discounted_price_rounding(self, make_product):
        product = make_product(price=Decimal("199.99"), discount=15)
        assert product.discounted_price == Decimal("169.99")


class TestFiltersSearchOrdering:
    @pytest.fixture
    def catalog(self, make_product, brand):
        other_cat = Category.objects.create(name="Laptops")
        return {
            "cheap": make_product(name="Budget phone", price=Decimal("50.00"), stock=0),
            "mid": make_product(name="Mid phone", price=Decimal("300.00"), discount=10),
            "pro": make_product(
                name="Pro laptop", price=Decimal("2000.00"), category=other_cat, brand=None
            ),
            "hidden": make_product(name="Old phone", is_active=False),
            "other_cat": other_cat,
        }

    def _names(self, client, **params):
        response = client.get(reverse("product-list"), params)
        assert response.status_code == 200
        return {p["name"] for p in _results(response)}

    def test_inactive_hidden_from_customers_visible_to_staff(
        self, api_client, staff_client, catalog
    ):
        assert "Old phone" not in self._names(api_client)
        assert "Old phone" in self._names(staff_client)

    def test_filters(self, api_client, catalog):
        assert self._names(api_client, price_min=100, price_max=500) == {"Mid phone"}
        assert self._names(api_client, category=catalog["other_cat"].pk) == {"Pro laptop"}
        assert self._names(api_client, in_stock="false") == {"Budget phone"}
        assert self._names(api_client, has_discount="true") == {"Mid phone"}

    def test_search_and_ordering(self, api_client, catalog):
        assert self._names(api_client, search="laptop") == {"Pro laptop"}
        response = api_client.get(reverse("product-list"), {"ordering": "-price"})
        prices = [p["price"] for p in _results(response)]
        assert prices == sorted(prices, key=Decimal, reverse=True)

    def test_rating_annotation_filter_and_order(self, api_client, catalog, user, other_user):
        Review.objects.create(user=user, product=catalog["mid"], rating=5)
        Review.objects.create(user=other_user, product=catalog["mid"], rating=4)
        Review.objects.create(user=user, product=catalog["cheap"], rating=2)
        assert self._names(api_client, rating_min=4) == {"Mid phone"}
        top = _results(api_client.get(reverse("product-list"), {"ordering": "-average_rating"}))[0]
        assert top["name"] == "Mid phone"
        assert top["average_rating"] == 4.5
        assert top["reviews_count"] == 2

    def test_pagination(self, api_client, make_product):
        for _ in range(5):
            make_product()
        response = api_client.get(reverse("product-list"), {"page_size": 2})
        body = response.json()
        assert body["count"] == 5
        assert len(body["results"]) == 2
        assert body["next"]


def test_product_list_has_no_n_plus_one(
    api_client, make_product, user, django_assert_max_num_queries
):
    for i in range(15):
        p = make_product()
        ProductImage.objects.create(
            product=p, image=SimpleUploadedFile(f"{i}.gif", GIF, "image/gif"), is_primary=True
        )
        Review.objects.create(user=user, product=p, rating=4)
    # count + page + primary images prefetch, regardless of page size
    with django_assert_max_num_queries(3):
        response = api_client.get(reverse("product-list"))
    assert response.status_code == 200
    assert all(p["primary_image"] for p in _results(response))


class TestNestedResources:
    def test_images_single_primary(self, staff_client, product, settings, tmp_path):
        settings.MEDIA_ROOT = tmp_path
        url = reverse("product-image-list", args=[product.pk])
        for name in ("a.gif", "b.gif"):
            response = staff_client.post(
                url,
                {"image": SimpleUploadedFile(name, GIF, "image/gif"), "is_primary": True},
                format="multipart",
            )
            assert response.status_code == 201, response.json()
        assert ProductImage.objects.filter(product=product, is_primary=True).count() == 1

    def test_field_values_validated_against_definition(self, staff_client, product):
        color = ProductField.objects.create(name="Color", field_type="choice", choices="Red, Blue")
        ram = ProductField.objects.create(name="RAM", field_type="number")
        url = reverse("product-field-value-list", args=[product.pk])
        assert staff_client.post(url, {"field": color.pk, "value": "Green"}).status_code == 400
        assert staff_client.post(url, {"field": ram.pk, "value": "lots"}).status_code == 400
        assert staff_client.post(url, {"field": color.pk, "value": "Red"}).status_code == 201
        assert staff_client.post(url, {"field": color.pk, "value": "Blue"}).status_code == 400
        detail = staff_client.get(reverse("product-detail", args=[product.pk])).json()
        assert detail["field_values"][0]["field_name"] == "Color"

    def test_choice_field_requires_choices(self, staff_client):
        response = staff_client.post(
            reverse("product-field-list"), {"name": "Size", "field_type": "choice"}
        )
        assert response.status_code == 400


def test_category_counts_only_active_products(api_client, make_product, category):
    make_product()
    make_product(is_active=False)
    data = api_client.get(reverse("category-detail", args=[category.pk])).json()
    assert data["products_count"] == 1


def test_order_snapshot_survives_product_deletion(make_order, user, product, staff_client):
    order = make_order(user, (product, 1), status=Order.Status.DELIVERED)
    assert staff_client.delete(reverse("product-detail", args=[product.pk])).status_code == 204
    item = order.items.get()
    assert item.product is None
    assert item.product_name == "Phone X"
