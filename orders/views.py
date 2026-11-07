from django.db.models import Prefetch
from drf_spectacular.utils import extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAdminUser, IsAuthenticated
from rest_framework.response import Response

from . import services
from .models import Order, OrderItem
from .serializers import CheckoutSerializer, OrderSerializer, OrderStatusSerializer


@extend_schema(tags=["orders"])
class OrderViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """Customers see their own orders; staff see everything."""

    serializer_class = OrderSerializer
    permission_classes = [IsAuthenticated]
    filterset_fields = ["status"]
    search_fields = ["user__email", "items__product_name"]
    ordering_fields = ["created", "total_amount"]

    queryset = Order.objects.none()

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Order.objects.none()
        qs = Order.objects.select_related("user").prefetch_related(
            Prefetch("items", OrderItem.objects.order_by("id"))
        )
        if self.request.user.is_staff:
            return qs
        return qs.filter(user=self.request.user)

    @extend_schema(request=CheckoutSerializer, responses={201: OrderSerializer})
    def create(self, request):
        """Checkout: create an order from the caller's own cart."""
        serializer = CheckoutSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        order = services.create_order_from_cart(request.user, **serializer.validated_data)
        order = self.get_queryset().get(pk=order.pk)
        return Response(OrderSerializer(order).data, status=status.HTTP_201_CREATED)

    @extend_schema(request=None, responses=OrderSerializer)
    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        """Customers may cancel their own order while it is still unpaid."""
        order = self.get_object()
        if not request.user.is_staff and order.status != Order.Status.PENDING:
            return Response(
                {"status": "Only unpaid orders can be cancelled. Contact support for refunds."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        services.change_status(order, Order.Status.CANCELLED)
        return Response(OrderSerializer(self.get_queryset().get(pk=order.pk)).data)

    @extend_schema(request=OrderStatusSerializer, responses=OrderSerializer)
    @action(detail=True, methods=["post"], permission_classes=[IsAdminUser], url_path="status")
    def set_status(self, request, pk=None):
        """Staff-only: move the order through shipped / delivered / cancelled."""
        order = self.get_object()
        serializer = OrderStatusSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.change_status(order, serializer.validated_data["status"])
        return Response(OrderSerializer(self.get_queryset().get(pk=order.pk)).data)
