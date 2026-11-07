from django.contrib import admin

from .models import Brand, Category, Product, ProductField, ProductFieldValue, ProductImage


class ProductImageInline(admin.TabularInline):
    model = ProductImage
    extra = 0


class ProductFieldValueInline(admin.TabularInline):
    model = ProductFieldValue
    extra = 0
    autocomplete_fields = ["field"]


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ["id", "name", "category", "brand", "price", "discount", "stock", "is_active"]
    list_filter = ["is_active", "category", "brand"]
    list_editable = ["stock", "is_active"]
    list_select_related = ["category", "brand"]
    search_fields = ["name", "description"]
    autocomplete_fields = ["category", "brand"]
    readonly_fields = ["created_by", "created", "updated"]
    inlines = [ProductImageInline, ProductFieldValueInline]

    def save_model(self, request, obj, form, change):
        if not change:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ["id", "name", "created"]
    search_fields = ["name"]


@admin.register(Brand)
class BrandAdmin(admin.ModelAdmin):
    list_display = ["id", "name", "created"]
    search_fields = ["name"]


@admin.register(ProductField)
class ProductFieldAdmin(admin.ModelAdmin):
    list_display = ["id", "name", "field_type"]
    search_fields = ["name"]
