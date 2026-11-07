from django.db import IntegrityError, transaction
from rest_framework import serializers

from products.models import Product

from .models import Cart, CartItem


class CartProductSerializer(serializers.ModelSerializer):
    class Meta:
        model = Product
        fields = ["id", "name", "price", "discount", "stock"]


class CartItemSerializer(serializers.ModelSerializer):
    product = CartProductSerializer(read_only=True)
    product_id = serializers.PrimaryKeyRelatedField(
        queryset=Product.objects.filter(is_active=True), source="product", write_only=True
    )
    quantity = serializers.IntegerField(min_value=1, max_value=1000)
    unit_price = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)
    total_price = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)

    class Meta:
        model = CartItem
        fields = [
            "id",
            "product",
            "product_id",
            "quantity",
            "unit_price",
            "total_price",
            "added_at",
        ]
        read_only_fields = ["added_at"]

    def validate(self, attrs):
        # Stock is only *checked* here (soft check for UX); it is reserved
        # atomically at checkout with a row lock, see orders.services.
        product = attrs.get("product") or self.instance.product
        quantity = attrs.get("quantity", 1)
        if self.instance is None:
            existing = CartItem.objects.filter(cart=self.context["cart"], product=product).first()
            if existing:
                quantity += existing.quantity
        if quantity > product.stock:
            raise serializers.ValidationError(
                {"quantity": f"Only {product.stock} item(s) of '{product.name}' in stock."}
            )
        return attrs

    def create(self, validated_data):
        cart = self.context["cart"]
        product = validated_data["product"]
        quantity = validated_data.get("quantity", 1)
        try:
            with transaction.atomic():
                item, created = CartItem.objects.select_for_update().get_or_create(
                    cart=cart, product=product, defaults={"quantity": quantity}
                )
                if not created:
                    item.quantity += quantity
                    item.save(update_fields=["quantity"])
        except IntegrityError:  # concurrent insert of the same product
            item = CartItem.objects.get(cart=cart, product=product)
        return item


class CartItemUpdateSerializer(CartItemSerializer):
    """PATCH only changes the quantity; the product is fixed."""

    def get_fields(self):
        fields = super().get_fields()
        fields.pop("product_id")
        return fields


class CartSerializer(serializers.ModelSerializer):
    items = CartItemSerializer(many=True, read_only=True)
    total_price = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)
    items_count = serializers.SerializerMethodField()

    class Meta:
        model = Cart
        fields = ["id", "items", "items_count", "total_price", "updated"]

    def get_items_count(self, obj) -> int:
        return sum(item.quantity for item in obj.items.all())
