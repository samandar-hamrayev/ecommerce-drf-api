"""Glue between payment providers and the order state machine."""

from orders.models import Order
from orders.services import change_status


def mark_order_paid(order: Order) -> None:
    change_status(order, Order.Status.PAID)


def refund_order(order: Order) -> None:
    """Cancel a paid order after the provider refunded it (restocks items)."""
    if order.status != Order.Status.CANCELLED:
        change_status(order, Order.Status.CANCELLED)
