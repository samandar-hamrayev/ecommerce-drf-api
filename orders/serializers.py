from rest_framework import serializers

from .models import Order, OrderItem


class OrderItemSerializer(serializers.ModelSerializer):
    line_total = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)

    class Meta:
        model = OrderItem
        fields = ["id", "product", "product_name", "unit_price", "quantity", "line_total"]
        read_only_fields = fields


class OrderSerializer(serializers.ModelSerializer):
    items = OrderItemSerializer(many=True, read_only=True)
    user = serializers.EmailField(source="user.email", read_only=True)

    class Meta:
        model = Order
        fields = [
            "id",
            "user",
            "status",
            "total_amount",
            "shipping_address",
            "phone",
            "items",
            "paid_at",
            "delivered_at",
            "cancelled_at",
            "created",
            "updated",
        ]
        read_only_fields = [f for f in fields if f not in ("shipping_address", "phone")]


class CheckoutSerializer(serializers.Serializer):
    shipping_address = serializers.CharField(max_length=500)
    phone = serializers.RegexField(r"^\+?\d{7,15}$", required=False, allow_blank=True)


class OrderStatusSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=Order.Status.choices)
