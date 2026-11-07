from drf_spectacular.utils import extend_schema
from rest_framework import viewsets
from rest_framework.permissions import SAFE_METHODS, AllowAny, IsAuthenticated

from core.permissions import IsOwnerOrReadOnly

from .models import Review
from .serializers import ReviewSerializer


@extend_schema(tags=["reviews"])
class ReviewViewSet(viewsets.ModelViewSet):
    """Public list of reviews; verified buyers may post one review per product."""

    queryset = Review.objects.select_related("user", "product")
    serializer_class = ReviewSerializer
    filterset_fields = ["product", "rating", "user"]
    search_fields = ["comment"]
    ordering_fields = ["created", "rating"]
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_permissions(self):
        if self.request.method in SAFE_METHODS:
            return [AllowAny()]
        return [IsAuthenticated(), IsOwnerOrReadOnly()]

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)
