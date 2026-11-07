from decimal import ROUND_HALF_UP, Decimal

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

MAX_DISCOUNT_PERCENT = 90
CENT = Decimal("0.01")


class Category(models.Model):
    name = models.CharField(max_length=255, unique=True)
    description = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_categories",
    )
    created = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "categories"

    def __str__(self):
        return self.name


class Brand(models.Model):
    name = models.CharField(max_length=255, unique=True)
    description = models.TextField(blank=True)
    logo = models.ImageField(upload_to="images/brand-logos/", blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_brands",
    )
    created = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Product(models.Model):
    name = models.CharField(max_length=255, unique=True)
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name="products")
    brand = models.ForeignKey(
        Brand, on_delete=models.SET_NULL, null=True, blank=True, related_name="products"
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_products",
    )
    description = models.TextField(blank=True)
    price = models.DecimalField(
        max_digits=14, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))]
    )
    stock = models.PositiveIntegerField(default=0)
    discount = models.PositiveSmallIntegerField(
        default=0,
        validators=[MinValueValidator(0), MaxValueValidator(MAX_DISCOUNT_PERCENT)],
        help_text="Discount in percent (0-90).",
    )
    is_active = models.BooleanField(default=True, help_text="Inactive products are hidden.")
    created = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created"]
        indexes = [
            models.Index(fields=["price"]),
            models.Index(fields=["created"]),
        ]
        constraints = [
            models.CheckConstraint(condition=models.Q(price__gt=0), name="product_price_positive"),
            models.CheckConstraint(
                condition=models.Q(discount__lte=MAX_DISCOUNT_PERCENT),
                name="product_discount_max_90",
            ),
        ]

    def __str__(self):
        return self.name

    @property
    def discounted_price(self) -> Decimal:
        """Unit price after the percentage discount, rounded to tiyin (0.01)."""
        factor = Decimal(100 - self.discount) / Decimal(100)
        return (self.price * factor).quantize(CENT, rounding=ROUND_HALF_UP)


class ProductImage(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="images")
    image = models.ImageField(upload_to="images/product-images/")
    alt_text = models.CharField(max_length=255, blank=True)
    is_primary = models.BooleanField(default=False)

    class Meta:
        ordering = ["-is_primary", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["product"],
                condition=models.Q(is_primary=True),
                name="one_primary_image_per_product",
            )
        ]

    def __str__(self):
        return f"Image #{self.pk} for product #{self.product_id}"


class ProductField(models.Model):
    """A dynamic attribute definition, e.g. "Color" or "RAM (GB)"."""

    class FieldType(models.TextChoices):
        TEXT = "text", "Text"
        NUMBER = "number", "Number"
        CHOICE = "choice", "Choice"

    name = models.CharField(max_length=100, unique=True)
    field_type = models.CharField(max_length=20, choices=FieldType.choices)
    choices = models.TextField(blank=True, help_text="Comma-separated options for choice fields.")

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    @property
    def choice_list(self) -> list[str]:
        return [c.strip() for c in self.choices.split(",") if c.strip()]


class ProductFieldValue(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="field_values")
    field = models.ForeignKey(ProductField, on_delete=models.CASCADE, related_name="values")
    value = models.CharField(max_length=255)

    class Meta:
        ordering = ["field__name"]
        constraints = [
            models.UniqueConstraint(fields=["product", "field"], name="unique_product_field")
        ]

    def __str__(self):
        return f"{self.field}: {self.value}"
