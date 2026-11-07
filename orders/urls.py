from django.urls import include, path
from rest_framework.routers import SimpleRouter

from .views import OrderViewSet

router = SimpleRouter()
router.register("orders", OrderViewSet, basename="order")

urlpatterns = [path("", include(router.urls))]
