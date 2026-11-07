from django.urls import include, path
from rest_framework_nested.routers import NestedSimpleRouter, SimpleRouter

from . import views

router = SimpleRouter()
router.register("categories", views.CategoryViewSet, basename="category")
router.register("brands", views.BrandViewSet, basename="brand")
router.register("products", views.ProductViewSet, basename="product")
router.register("product-fields", views.ProductFieldViewSet, basename="product-field")

product_router = NestedSimpleRouter(router, "products", lookup="product")
product_router.register("images", views.ProductImageViewSet, basename="product-image")
product_router.register(
    "field-values", views.ProductFieldValueViewSet, basename="product-field-value"
)

urlpatterns = [
    path("", include(router.urls)),
    path("", include(product_router.urls)),
]
