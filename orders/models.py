from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models

from products.models import Product


class Order(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending payment"
        PAID = "paid", "Paid"
        SHIPPED = "shipped", "Shipped"
        DELIVERED = "delivered", "Delivered"
        CANCELLED = "cancelled", "Cancelled"

    # Allowed state machine edges. Anything else is rejected by the service layer.
    TRANSITIONS: dict[str, set[str]] = {
        Status.PENDING: {Status.PAID, Status.CANCELLED},
        Status.PAID: {Status.SHIPPED, Status.CANCELLED},
        Status.SHIPPED: {Status.DELIVERED},
        Status.DELIVERED: set(),
        Status.CANCELLED: set(),
    }

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="orders"
    )
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    total_amount = models.DecimalField(
        max_digits=14, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))]
    )
    shipping_address = models.CharField(max_length=500)
    phone = models.CharField(max_length=20, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    created = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created"]
        indexes = [models.Index(fields=["user", "status"])]

    def __str__(self):
        return f"Order #{self.pk} ({self.status})"

    def can_transition_to(self, new_status: str) -> bool:
        return new_status in self.TRANSITIONS[self.status]

    @property
    def is_payable(self) -> bool:
        return self.status == self.Status.PENDING


class OrderItem(models.Model):
    """A line of an order. Name and price are *snapshots* taken at checkout,
    so later catalog edits never change what the customer was charged."""

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey(
        Product, on_delete=models.SET_NULL, null=True, related_name="order_items"
    )
    product_name = models.CharField(max_length=255)
    unit_price = models.DecimalField(max_digits=14, decimal_places=2)
    quantity = models.PositiveIntegerField(validators=[MinValueValidator(1)])

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return f"{self.quantity} x {self.product_name}"

    @property
    def line_total(self) -> Decimal:
        return self.unit_price * self.quantity
