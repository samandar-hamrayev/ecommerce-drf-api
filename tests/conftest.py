from decimal import Decimal

import pytest
from django.core.cache import cache
from rest_framework.test import APIClient

from carts.models import Cart, CartItem
from orders.models import Order
from orders.services import create_order_from_cart
from products.models import Brand, Category, Product
from users.models import User

PASSWORD = "correct-horse-battery"


@pytest.fixture(autouse=True)
def _fast_and_isolated(settings):
    settings.PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    cache.clear()  # reset throttling counters between tests


@pytest.fixture
def api_client():
    return APIClient()


def _make_user(email, **extra):
    extra.setdefault("is_active", True)
    return User.objects.create_user(email=email, password=PASSWORD, first_name="Test", **extra)


@pytest.fixture
def user(db):
    return _make_user("alice@example.com", last_name="Alice")


@pytest.fixture
def other_user(db):
    return _make_user("bob@example.com", last_name="Bob")


@pytest.fixture
def staff(db):
    return _make_user("staff@example.com", is_staff=True)


@pytest.fixture
def client_for():
    def _client(u):
        client = APIClient()
        client.force_authenticate(u)
        return client

    return _client


@pytest.fixture
def user_client(client_for, user):
    return client_for(user)


@pytest.fixture
def staff_client(client_for, staff):
    return client_for(staff)


@pytest.fixture
def category(db):
    return Category.objects.create(name="Phones")


@pytest.fixture
def brand(db):
    return Brand.objects.create(name="Acme")


@pytest.fixture
def make_product(category, brand):
    counter = {"n": 0}

    def _make(**kwargs):
        counter["n"] += 1
        defaults = {
            "name": f"Product {counter['n']}",
            "category": category,
            "brand": brand,
            "price": Decimal("100000.00"),
            "stock": 10,
        }
        defaults.update(kwargs)
        return Product.objects.create(**defaults)

    return _make


@pytest.fixture
def product(make_product):
    return make_product(name="Phone X", price=Decimal("150000.00"), stock=5)


@pytest.fixture
def fill_cart():
    def _fill(u, *pairs):
        cart, _ = Cart.objects.get_or_create(user=u)
        for prod, qty in pairs:
            CartItem.objects.create(cart=cart, product=prod, quantity=qty)
        return cart

    return _fill


@pytest.fixture
def make_order(fill_cart):
    """Create a real order through the service layer."""

    def _make(u, *pairs, status=None):
        fill_cart(u, *pairs)
        order = create_order_from_cart(u, shipping_address="Tashkent, Amir Temur 1")
        if status:
            Order.objects.filter(pk=order.pk).update(status=status)
            order.refresh_from_db()
        return order

    return _make
