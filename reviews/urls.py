from django.urls import include, path
from rest_framework.routers import SimpleRouter

from .views import ReviewViewSet

router = SimpleRouter()
router.register("reviews", ReviewViewSet, basename="review")

urlpatterns = [path("", include(router.urls))]
