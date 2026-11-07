from django.contrib import admin

from .models import Order, OrderItem


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    readonly_fields = ["product", "product_name", "unit_price", "quantity"]
    can_delete = False


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ["id", "user", "status", "total_amount", "created", "paid_at"]
    list_filter = ["status", "created"]
    list_select_related = ["user"]
    search_fields = ["id", "user__email"]
    # Status changes go through the API so the state machine and restocking apply.
    readonly_fields = [
        "user",
        "status",
        "total_amount",
        "paid_at",
        "delivered_at",
        "cancelled_at",
        "created",
    ]
    inlines = [OrderItemInline]
