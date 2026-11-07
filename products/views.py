from django.db.models import Avg, Count, Prefetch, ProtectedError, Q
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework import status, viewsets
from rest_framework.response import Response

from core.permissions import IsStaffOrReadOnly

from .filters import ProductFilter
from .models import Brand, Category, Product, ProductField, ProductFieldValue, ProductImage
from .serializers import (
    BrandSerializer,
    CategorySerializer,
    ProductDetailSerializer,
    ProductFieldSerializer,
    ProductFieldValueSerializer,
    ProductImageSerializer,
    ProductListSerializer,
)

ACTIVE_PRODUCTS = Count("products", filter=Q(products__is_active=True))


@extend_schema(tags=["catalog"])
class CategoryViewSet(viewsets.ModelViewSet):
    queryset = Category.objects.annotate(products_count=ACTIVE_PRODUCTS).order_by("name")
    serializer_class = CategorySerializer
    permission_classes = [IsStaffOrReadOnly]
    search_fields = ["name", "description"]
    ordering_fields = ["name", "created", "products_count"]

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    def destroy(self, request, *args, **kwargs):
        try:
            return super().destroy(request, *args, **kwargs)
        except ProtectedError:
            return Response(
                {"detail": "Category still has products; move or delete them first."},
                status=status.HTTP_409_CONFLICT,
            )


@extend_schema(tags=["catalog"])
class BrandViewSet(CategoryViewSet):
    queryset = Brand.objects.annotate(products_count=ACTIVE_PRODUCTS).order_by("name")
    serializer_class = BrandSerializer


@extend_schema(tags=["catalog"])
class ProductViewSet(viewsets.ModelViewSet):
    """Catalog. Reads are public; writes require a staff account."""

    permission_classes = [IsStaffOrReadOnly]
    filterset_class = ProductFilter
    search_fields = ["name", "description", "brand__name", "category__name"]
    ordering_fields = ["price", "created", "name", "stock", "average_rating", "discount"]
    ordering = ["-created"]

    def get_queryset(self):
        qs = (
            Product.objects.select_related("category", "brand")
            .annotate(
                average_rating=Avg("reviews__rating"),
                reviews_count=Count("reviews", distinct=True),
            )
            .order_by("-created")
        )
        if self.action == "list":
            qs = qs.prefetch_related(
                Prefetch("images", queryset=ProductImage.objects.filter(is_primary=True))
            )
        else:
            qs = qs.prefetch_related(
                "images",
                Prefetch("field_values", ProductFieldValue.objects.select_related("field")),
            )
        user = self.request.user
        if not (user.is_authenticated and user.is_staff):
            qs = qs.filter(is_active=True)
        return qs

    def get_serializer_class(self):
        return ProductListSerializer if self.action == "list" else ProductDetailSerializer

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)


@extend_schema(tags=["catalog"])
class ProductFieldViewSet(viewsets.ModelViewSet):
    queryset = ProductField.objects.all()
    serializer_class = ProductFieldSerializer
    permission_classes = [IsStaffOrReadOnly]
    filterset_fields = ["field_type"]
    search_fields = ["name"]


class _ProductChildViewSet(viewsets.ModelViewSet):
    """Base for resources nested under ``/products/{product_pk}/``."""

    permission_classes = [IsStaffOrReadOnly]
    model = None

    def get_product(self):
        if not hasattr(self, "_product"):
            self._product = get_object_or_404(Product, pk=self.kwargs["product_pk"])
        return self._product

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return self.model.objects.none()
        return self.model.objects.filter(product_id=self.kwargs["product_pk"])

    def get_serializer_context(self):
        context = super().get_serializer_context()
        if "product_pk" in self.kwargs:
            context["product"] = self.get_product()
        return context

    def perform_create(self, serializer):
        serializer.save(product=self.get_product())


@extend_schema(tags=["catalog"])
class ProductImageViewSet(_ProductChildViewSet):
    model = ProductImage
    serializer_class = ProductImageSerializer
    filterset_fields = ["is_primary"]

    def _demote_other_primary(self, serializer):
        if serializer.validated_data.get("is_primary"):
            ProductImage.objects.filter(product=self.get_product(), is_primary=True).update(
                is_primary=False
            )

    def perform_create(self, serializer):
        self._demote_other_primary(serializer)
        super().perform_create(serializer)

    def perform_update(self, serializer):
        self._demote_other_primary(serializer)
        serializer.save()


@extend_schema(tags=["catalog"])
class ProductFieldValueViewSet(_ProductChildViewSet):
    model = ProductFieldValue
    serializer_class = ProductFieldValueSerializer

    def get_queryset(self):
        return super().get_queryset().select_related("field")
