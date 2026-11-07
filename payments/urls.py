from django.urls import path

from . import views

urlpatterns = [
    path("checkout/", views.CheckoutView.as_view(), name="payment-checkout"),
    path("click/prepare/", views.ClickPrepareView.as_view(), name="click-prepare"),
    path("click/complete/", views.ClickCompleteView.as_view(), name="click-complete"),
]
