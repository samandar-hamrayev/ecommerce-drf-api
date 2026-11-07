from rest_framework import serializers

from orders.models import Order, OrderItem
from products.models import Product

from .models import Review


class ReviewSerializer(serializers.ModelSerializer):
    user = serializers.CharField(source="user.full_name", read_only=True)
    product = serializers.PrimaryKeyRelatedField(queryset=Product.objects.filter(is_active=True))

    class Meta:
        model = Review
        fields = ["id", "user", "product", "rating", "comment", "created", "updated"]
        read_only_fields = ["created", "updated"]

    def validate_product(self, product):
        if self.instance is not None and product != self.instance.product:
            raise serializers.ValidationError("The product of a review cannot be changed.")
        return product

    def validate(self, attrs):
        if self.instance is not None:
            return attrs
        user = self.context["request"].user
        product = attrs["product"]
        if Review.objects.filter(user=user, product=product).exists():
            raise serializers.ValidationError(
                {"product": "You have already reviewed this product."}
            )
        purchased = OrderItem.objects.filter(
            order__user=user, order__status=Order.Status.DELIVERED, product=product
        ).exists()
        if not purchased:
            raise serializers.ValidationError(
                {"product": "You can only review products from your delivered orders."}
            )
        return attrs
