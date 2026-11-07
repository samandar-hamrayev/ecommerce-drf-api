from django_filters import rest_framework as filters

from .models import Product


class ProductFilter(filters.FilterSet):
    category = filters.NumberFilter(field_name="category_id")
    brand = filters.NumberFilter(field_name="brand_id")
    price_min = filters.NumberFilter(field_name="price", lookup_expr="gte")
    price_max = filters.NumberFilter(field_name="price", lookup_expr="lte")
    in_stock = filters.BooleanFilter(method="filter_in_stock")
    has_discount = filters.BooleanFilter(method="filter_has_discount")
    rating_min = filters.NumberFilter(field_name="average_rating", lookup_expr="gte")

    class Meta:
        model = Product
        fields = ["category", "brand"]

    def filter_in_stock(self, queryset, name, value):
        return queryset.filter(stock__gt=0) if value else queryset.filter(stock=0)

    def filter_has_discount(self, queryset, name, value):
        return queryset.filter(discount__gt=0) if value else queryset.filter(discount=0)
