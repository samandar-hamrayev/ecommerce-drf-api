from rest_framework import serializers

from .models import Brand, Category, Product, ProductField, ProductFieldValue, ProductImage


class CategorySerializer(serializers.ModelSerializer):
    products_count = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = Category
        fields = ["id", "name", "description", "products_count", "created", "updated"]
        read_only_fields = ["created", "updated"]


class BrandSerializer(serializers.ModelSerializer):
    products_count = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = Brand
        fields = ["id", "name", "description", "logo", "products_count", "created", "updated"]
        read_only_fields = ["created", "updated"]


class CategoryRefSerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ["id", "name"]


class BrandRefSerializer(serializers.ModelSerializer):
    class Meta:
        model = Brand
        fields = ["id", "name"]


class ProductImageSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductImage
        fields = ["id", "image", "alt_text", "is_primary"]


class ProductFieldSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductField
        fields = ["id", "name", "field_type", "choices"]

    def validate(self, attrs):
        field_type = attrs.get("field_type", getattr(self.instance, "field_type", None))
        choices = attrs.get("choices", getattr(self.instance, "choices", ""))
        if field_type == ProductField.FieldType.CHOICE and not choices.strip():
            raise serializers.ValidationError(
                {"choices": "Choice fields need at least one option."}
            )
        return attrs


class ProductFieldValueSerializer(serializers.ModelSerializer):
    field_name = serializers.CharField(source="field.name", read_only=True)

    class Meta:
        model = ProductFieldValue
        fields = ["id", "field", "field_name", "value"]

    def validate(self, attrs):
        field = attrs.get("field", getattr(self.instance, "field", None))
        value = attrs.get("value", getattr(self.instance, "value", ""))
        if field.field_type == ProductField.FieldType.NUMBER:
            try:
                float(value)
            except ValueError:
                raise serializers.ValidationError({"value": "Must be a number."}) from None
        if field.field_type == ProductField.FieldType.CHOICE and value not in field.choice_list:
            raise serializers.ValidationError(
                {"value": f"Must be one of: {', '.join(field.choice_list)}."}
            )
        product = self.context["product"]
        duplicate = ProductFieldValue.objects.filter(product=product, field=field)
        if self.instance is not None:
            duplicate = duplicate.exclude(pk=self.instance.pk)
        if duplicate.exists():
            raise serializers.ValidationError({"field": "This product already has a value for it."})
        return attrs


class ProductListSerializer(serializers.ModelSerializer):
    category = CategoryRefSerializer(read_only=True)
    brand = BrandRefSerializer(read_only=True)
    discounted_price = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)
    average_rating = serializers.FloatField(read_only=True, allow_null=True, default=None)
    reviews_count = serializers.IntegerField(read_only=True, default=0)
    primary_image = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = [
            "id",
            "name",
            "category",
            "brand",
            "price",
            "discount",
            "discounted_price",
            "stock",
            "average_rating",
            "reviews_count",
            "primary_image",
            "created",
        ]

    def get_primary_image(self, obj) -> str | None:
        # Uses the ``images`` prefetch from the viewset: no extra query per row.
        primary = next((img for img in obj.images.all() if img.is_primary), None)
        if primary is None:
            return None
        url = primary.image.url
        request = self.context.get("request")
        return request.build_absolute_uri(url) if request else url


class ProductDetailSerializer(ProductListSerializer):
    category_id = serializers.PrimaryKeyRelatedField(
        queryset=Category.objects.all(), source="category", write_only=True
    )
    brand_id = serializers.PrimaryKeyRelatedField(
        queryset=Brand.objects.all(),
        source="brand",
        write_only=True,
        required=False,
        allow_null=True,
    )
    images = ProductImageSerializer(many=True, read_only=True)
    field_values = ProductFieldValueSerializer(many=True, read_only=True)

    class Meta(ProductListSerializer.Meta):
        fields = [
            *ProductListSerializer.Meta.fields,
            "category_id",
            "brand_id",
            "description",
            "is_active",
            "images",
            "field_values",
            "updated",
        ]
