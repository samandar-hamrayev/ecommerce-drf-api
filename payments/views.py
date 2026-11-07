from django.conf import settings
from django.shortcuts import get_object_or_404
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiExample, extend_schema
from rest_framework import status
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from orders.models import Order

from .providers import ClickProvider, PaymeProvider, get_provider
from .serializers import CheckoutRequestSerializer, CheckoutResponseSerializer


class ProviderCallbackView(APIView):
    """Server-to-server callbacks: no user auth (requests are verified by
    signature / Basic auth inside the provider), no CSRF, no throttling."""

    authentication_classes: list = []
    permission_classes = [AllowAny]
    throttle_classes: list = []


@extend_schema(tags=["payments"])
class CheckoutView(APIView):
    """Return the hosted payment page URL for one of the caller's unpaid orders."""

    permission_classes = [IsAuthenticated]

    @extend_schema(request=CheckoutRequestSerializer, responses=CheckoutResponseSerializer)
    def post(self, request):
        serializer = CheckoutRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        order = get_object_or_404(Order, pk=data["order"], user=request.user)
        if not order.is_payable:
            return Response(
                {"order": "Only pending orders can be paid."}, status=status.HTTP_400_BAD_REQUEST
            )
        provider = get_provider(data["provider"])
        if not provider.is_configured():
            return Response(
                {"provider": f"{data['provider']} is not configured on this server."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        return_url = data.get("return_url") or settings.PAYMENT_RETURN_URL
        return Response(
            {
                "provider": provider.name,
                "order": order.pk,
                "amount": order.total_amount,
                "checkout_url": provider.build_checkout_url(order, return_url),
            }
        )


def _click_params(request) -> dict:
    return {key: request.data.get(key) for key in request.data}


CLICK_EXAMPLE = OpenApiExample(
    "Prepare",
    value={
        "click_trans_id": "2275614",
        "service_id": "12345",
        "click_paydoc_id": "3350123",
        "merchant_trans_id": "42",
        "amount": "150000.00",
        "action": "0",
        "error": "0",
        "error_note": "Success",
        "sign_time": "2026-11-07 12:00:00",
        "sign_string": "<md5>",
    },
    request_only=True,
)


@extend_schema(
    tags=["payments"],
    request={"application/x-www-form-urlencoded": OpenApiTypes.OBJECT},
    responses=OpenApiTypes.OBJECT,
    examples=[CLICK_EXAMPLE],
    summary="Click SHOP-API Prepare callback (action=0)",
)
class ClickPrepareView(ProviderCallbackView):
    parser_classes = [FormParser, MultiPartParser, JSONParser]

    def post(self, request):
        return Response(ClickProvider().prepare(_click_params(request)))


@extend_schema(
    tags=["payments"],
    request={"application/x-www-form-urlencoded": OpenApiTypes.OBJECT},
    responses=OpenApiTypes.OBJECT,
    summary="Click SHOP-API Complete callback (action=1)",
)
class ClickCompleteView(ProviderCallbackView):
    parser_classes = [FormParser, MultiPartParser, JSONParser]

    def post(self, request):
        return Response(ClickProvider().complete(_click_params(request)))


@extend_schema(
    tags=["payments"],
    request=OpenApiTypes.OBJECT,
    responses=OpenApiTypes.OBJECT,
    summary="Payme Merchant API (JSON-RPC 2.0) endpoint",
    examples=[
        OpenApiExample(
            "CheckPerformTransaction",
            value={
                "id": 1,
                "method": "CheckPerformTransaction",
                "params": {"amount": 15000000, "account": {"order_id": "42"}},
            },
            request_only=True,
        )
    ],
)
class PaymeView(ProviderCallbackView):
    parser_classes: list = []  # we read the raw body to report -32700 ourselves

    def post(self, request):
        body = PaymeProvider().handle(request.body, request.META.get("HTTP_AUTHORIZATION"))
        return Response(body, status=status.HTTP_200_OK)
