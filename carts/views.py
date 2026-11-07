from django.db.models import Prefetch
from drf_spectacular.utils import extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Cart, CartItem
from .serializers import CartItemSerializer, CartItemUpdateSerializer, CartSerializer


def get_cart(user) -> Cart:
    cart, _ = Cart.objects.get_or_create(user=user)
    return cart


@extend_schema(tags=["cart"])
class CartView(APIView):
    """The authenticated user's cart (created lazily on first access)."""

    permission_classes = [IsAuthenticated]

    @extend_schema(responses=CartSerializer)
    def get(self, request):
        get_cart(request.user)
        cart = Cart.objects.prefetch_related(
            Prefetch("items", CartItem.objects.select_related("product"))
        ).get(user=request.user)
        return Response(CartSerializer(cart, context={"request": request}).data)

    @extend_schema(responses={204: None})
    def delete(self, request):
        CartItem.objects.filter(cart__user=request.user).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


@extend_schema(tags=["cart"])
class CartItemViewSet(
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    permission_classes = [IsAuthenticated]
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]
    pagination_class = None
    ordering = ["-added_at"]

    queryset = CartItem.objects.none()

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return CartItem.objects.none()
        # Scoped to the caller: other users' items are simply not found (404).
        return CartItem.objects.filter(cart__user=self.request.user).select_related("product")

    def get_serializer_class(self):
        if self.action in ("update", "partial_update"):
            return CartItemUpdateSerializer
        return CartItemSerializer

    def get_serializer_context(self):
        context = super().get_serializer_context()
        if self.request.user.is_authenticated:
            context["cart"] = get_cart(self.request.user)
        return context
