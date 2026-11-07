from django.db import models

from orders.models import Order


class Payment(models.Model):
    """One provider-side transaction for an order.

    ``state`` uses Payme's numeric states, which are a superset of what Click
    needs, so both providers share one table and one state machine:

        CREATED(1) -> PERFORMED(2) -> CANCELLED_AFTER_PERFORM(-2)
             \\-> CANCELLED(-1)
    """

    class Provider(models.TextChoices):
        CLICK = "click", "Click"
        PAYME = "payme", "Payme"

    class State(models.IntegerChoices):
        CREATED = 1, "Created"
        PERFORMED = 2, "Performed"
        CANCELLED = -1, "Cancelled"
        CANCELLED_AFTER_PERFORM = -2, "Cancelled after perform (refund)"

    provider = models.CharField(max_length=16, choices=Provider.choices)
    external_id = models.CharField(
        max_length=64, help_text="click_trans_id for Click, transaction id for Payme."
    )
    order = models.ForeignKey(Order, on_delete=models.PROTECT, related_name="payments")
    amount = models.DecimalField(max_digits=14, decimal_places=2, help_text="Amount in UZS.")
    state = models.SmallIntegerField(choices=State.choices, default=State.CREATED)
    reason = models.SmallIntegerField(null=True, blank=True, help_text="Cancel reason code.")
    provider_time = models.BigIntegerField(
        null=True, blank=True, help_text="Provider-side creation time (ms since epoch)."
    )
    extra = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    performed_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            # Idempotency guarantee at the DB level: a provider transaction id
            # can only ever map to one row, even under concurrent retries.
            models.UniqueConstraint(
                fields=["provider", "external_id"], name="unique_provider_transaction"
            )
        ]
        indexes = [
            models.Index(fields=["provider", "state"]),
            models.Index(fields=["provider", "provider_time"]),
        ]

    def __str__(self):
        return f"{self.provider}:{self.external_id} order#{self.order_id} state={self.state}"
