from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models

from products.models import Product


class Cart(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="cart"
    )
    created = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Cart of {self.user}"

    @property
    def total_price(self) -> Decimal:
        # Callers prefetch ``items__product`` so this does not hit the DB per item.
        return sum((item.total_price for item in self.items.all()), Decimal("0.00"))


class CartItem(models.Model):
    cart = models.ForeignKey(Cart, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="cart_items")
    quantity = models.PositiveIntegerField(default=1, validators=[MinValueValidator(1)])
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-added_at"]
        constraints = [
            models.UniqueConstraint(fields=["cart", "product"], name="unique_cart_product"),
            models.CheckConstraint(condition=models.Q(quantity__gte=1), name="cart_item_qty_gte_1"),
        ]

    def __str__(self):
        return f"{self.quantity} x {self.product}"

    @property
    def unit_price(self) -> Decimal:
        return self.product.discounted_price

    @property
    def total_price(self) -> Decimal:
        return self.unit_price * self.quantity
