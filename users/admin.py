from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import EmailVerification, User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    ordering = ["-created"]
    list_display = ["id", "email", "first_name", "last_name", "is_active", "is_staff", "created"]
    list_filter = ["is_active", "is_staff", "is_superuser", "gender"]
    search_fields = ["email", "first_name", "last_name"]
    readonly_fields = ["created", "updated", "last_login"]
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Profile", {"fields": ("first_name", "last_name", "gender", "born_date", "avatar")}),
        (
            "Permissions",
            {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")},
        ),
        ("Dates", {"fields": ("last_login", "created", "updated")}),
    )
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("email", "first_name", "last_name", "password1", "password2"),
            },
        ),
    )


@admin.register(EmailVerification)
class EmailVerificationAdmin(admin.ModelAdmin):
    list_display = ["user", "created", "expires", "is_used"]
    list_select_related = ["user"]
    exclude = ["code"]
