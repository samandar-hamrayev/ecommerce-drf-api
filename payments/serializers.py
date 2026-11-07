from rest_framework import serializers

from .models import Payment
from .providers import PROVIDERS


class CheckoutRequestSerializer(serializers.Serializer):
    order = serializers.IntegerField(min_value=1)
    provider = serializers.ChoiceField(choices=sorted(PROVIDERS))
    return_url = serializers.URLField(required=False, allow_blank=True)


class CheckoutResponseSerializer(serializers.Serializer):
    provider = serializers.CharField()
    order = serializers.IntegerField()
    amount = serializers.DecimalField(max_digits=14, decimal_places=2)
    checkout_url = serializers.URLField()


class PaymentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Payment
        fields = ["id", "provider", "order", "amount", "state", "created_at", "performed_at"]
