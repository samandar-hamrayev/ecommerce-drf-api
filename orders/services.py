"""Order business logic. Views stay thin; every state change goes through here."""

from decimal import Decimal

from django.db import transaction
from django.db.models import F
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from carts.models import CartItem
from products.models import Product

from .models import Order, OrderItem


class OrderError(ValidationError):
    pass


@transaction.atomic
def create_order_from_cart(user, *, shipping_address: str, phone: str = "") -> Order:
    """Turn the user's cart into an order.

    * Locks the involved product rows (``SELECT ... FOR UPDATE``, ordered by id
      to avoid deadlocks) so two concurrent checkouts can't oversell stock.
    * Snapshots name and discounted price into ``OrderItem``.
    * Everything happens in one transaction: on any error nothing is written.
    """
    cart_items = list(
        CartItem.objects.select_for_update().filter(cart__user=user).order_by("product_id")
    )
    if not cart_items:
        raise OrderError({"cart": "Your cart is empty."})

    products = {
        p.pk: p
        for p in Product.objects.select_for_update()
        .filter(pk__in=[item.product_id for item in cart_items])
        .order_by("pk")
    }

    errors = []
    for item in cart_items:
        product = products[item.product_id]
        if not product.is_active:
            errors.append(f"'{product.name}' is no longer available.")
        elif item.quantity > product.stock:
            errors.append(f"Only {product.stock} item(s) of '{product.name}' left in stock.")
    if errors:
        raise OrderError({"cart": errors})

    order_items = []
    total = Decimal("0.00")
    for item in cart_items:
        product = products[item.product_id]
        unit_price = product.discounted_price
        total += unit_price * item.quantity
        order_items.append(
            OrderItem(
                product=product,
                product_name=product.name,
                unit_price=unit_price,
                quantity=item.quantity,
            )
        )
        Product.objects.filter(pk=product.pk).update(stock=F("stock") - item.quantity)

    order = Order.objects.create(
        user=user, total_amount=total, shipping_address=shipping_address, phone=phone
    )
    for order_item in order_items:
        order_item.order = order
    OrderItem.objects.bulk_create(order_items)
    CartItem.objects.filter(pk__in=[item.pk for item in cart_items]).delete()
    return order


def _restock(order: Order) -> None:
    for item in order.items.all():
        if item.product_id:
            Product.objects.filter(pk=item.product_id).update(stock=F("stock") + item.quantity)


@transaction.atomic
def change_status(order: Order, new_status: str) -> Order:
    """Move an order along the state machine, applying side effects."""
    order = Order.objects.select_for_update().get(pk=order.pk)
    if not order.can_transition_to(new_status):
        raise OrderError(
            {"status": f"Cannot change status from '{order.status}' to '{new_status}'."}
        )

    now = timezone.now()
    update_fields = ["status", "updated"]
    if new_status == Order.Status.CANCELLED:
        _restock(order)
        order.cancelled_at = now
        update_fields.append("cancelled_at")
    elif new_status == Order.Status.PAID:
        order.paid_at = now
        update_fields.append("paid_at")
    elif new_status == Order.Status.DELIVERED:
        order.delivered_at = now
        update_fields.append("delivered_at")

    order.status = new_status
    order.save(update_fields=update_fields)
    return order
