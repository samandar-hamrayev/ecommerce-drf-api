from django.contrib import admin

from .models import Payment


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ["id", "provider", "external_id", "order", "amount", "state", "created_at"]
    list_filter = ["provider", "state"]
    list_select_related = ["order"]
    search_fields = ["external_id", "order__id"]
    readonly_fields = [f.name for f in Payment._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
