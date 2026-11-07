from django.contrib import admin

from .models import Review


@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
    list_display = ["id", "product", "user", "rating", "created"]
    list_filter = ["rating"]
    list_select_related = ["product", "user"]
    search_fields = ["comment", "user__email", "product__name"]
