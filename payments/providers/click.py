"""Click SHOP-API merchant callbacks (Prepare / Complete).

Click calls the merchant twice, with ``application/x-www-form-urlencoded`` POSTs:

1. **Prepare** (``action=0``): "can this order be paid with this amount?"
   The merchant reserves a transaction and returns ``merchant_prepare_id``.
2. **Complete** (``action=1``): "the money was charged (or not, if ``error<0``)".
   The merchant finalises the transaction and returns ``merchant_confirm_id``.

Each request is signed with ``sign_string``::

    prepare:  md5(click_trans_id + service_id + SECRET_KEY + merchant_trans_id
                  + amount + action + sign_time)
    complete: md5(click_trans_id + service_id + SECRET_KEY + merchant_trans_id
                  + merchant_prepare_id + amount + action + sign_time)

The responses always use HTTP 200 and carry the result in ``error`` /
``error_note``. In this project ``merchant_trans_id`` is the order id.
"""

import hashlib
import hmac
import logging
from decimal import Decimal, InvalidOperation
from enum import IntEnum
from urllib.parse import urlencode

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from orders.models import Order
from payments import services
from payments.models import Payment

from .base import PaymentProvider

logger = logging.getLogger(__name__)

CHECKOUT_URL = "https://my.click.uz/services/pay"

ACTION_PREPARE = 0
ACTION_COMPLETE = 1

PREPARE_FIELDS = (
    "click_trans_id",
    "service_id",
    "click_paydoc_id",
    "merchant_trans_id",
    "amount",
    "action",
    "error",
    "error_note",
    "sign_time",
    "sign_string",
)
COMPLETE_FIELDS = (*PREPARE_FIELDS, "merchant_prepare_id")


class ClickError(IntEnum):
    SUCCESS = 0
    SIGN_CHECK_FAILED = -1
    INVALID_AMOUNT = -2
    ACTION_NOT_FOUND = -3
    ALREADY_PAID = -4
    USER_NOT_FOUND = -5  # "User does not exist" - here: order not found
    TRANSACTION_NOT_FOUND = -6
    FAILED_TO_UPDATE = -7
    BAD_REQUEST = -8  # "Error in request from click"
    TRANSACTION_CANCELLED = -9


ERROR_NOTES = {
    ClickError.SUCCESS: "Success",
    ClickError.SIGN_CHECK_FAILED: "SIGN CHECK FAILED!",
    ClickError.INVALID_AMOUNT: "Incorrect parameter amount",
    ClickError.ACTION_NOT_FOUND: "Action not found",
    ClickError.ALREADY_PAID: "Already paid",
    ClickError.USER_NOT_FOUND: "User does not exist",
    ClickError.TRANSACTION_NOT_FOUND: "Transaction does not exist",
    ClickError.FAILED_TO_UPDATE: "Failed to update user",
    ClickError.BAD_REQUEST: "Error in request from click",
    ClickError.TRANSACTION_CANCELLED: "Transaction cancelled",
}


class _Reject(Exception):  # noqa: N818 - internal control-flow signal
    def __init__(self, code: ClickError):
        self.code = code


def build_sign(params: dict, secret_key: str, action: int) -> str:
    """Compute the md5 ``sign_string`` exactly as Click does, from raw strings."""
    parts = [
        params["click_trans_id"],
        params["service_id"],
        secret_key,
        params["merchant_trans_id"],
    ]
    if action == ACTION_COMPLETE:
        parts.append(params["merchant_prepare_id"])
    parts += [params["amount"], params["action"], params["sign_time"]]
    return hashlib.md5("".join(str(p) for p in parts).encode()).hexdigest()  # noqa: S324 - mandated by Click


class ClickProvider(PaymentProvider):
    name = Payment.Provider.CLICK

    def __init__(self):
        self.service_id = str(settings.CLICK_SERVICE_ID)
        self.merchant_id = str(settings.CLICK_MERCHANT_ID)
        self.secret_key = settings.CLICK_SECRET_KEY

    # ------------------------------------------------------------------ checkout
    def is_configured(self) -> bool:
        return bool(self.service_id and self.merchant_id and self.secret_key)

    def build_checkout_url(self, order: Order, return_url: str = "") -> str:
        query = {
            "service_id": self.service_id,
            "merchant_id": self.merchant_id,
            "amount": f"{order.total_amount:.2f}",
            "transaction_param": str(order.pk),
        }
        if return_url:
            query["return_url"] = return_url
        return f"{CHECKOUT_URL}?{urlencode(query)}"

    # ----------------------------------------------------------------- callbacks
    def prepare(self, params: dict) -> dict:
        return self._handle(params, ACTION_PREPARE)

    def complete(self, params: dict) -> dict:
        return self._handle(params, ACTION_COMPLETE)

    def _handle(self, params: dict, expected_action: int) -> dict:
        response = {
            "click_trans_id": params.get("click_trans_id"),
            "merchant_trans_id": params.get("merchant_trans_id"),
        }
        try:
            self._validate_request(params, expected_action)
            if expected_action == ACTION_PREPARE:
                response["merchant_prepare_id"] = self._prepare(params)
                code = ClickError.SUCCESS
            else:
                code, confirm_id = self._complete(params)
                if code == ClickError.SUCCESS:
                    response["merchant_confirm_id"] = confirm_id
        except _Reject as reject:
            code = reject.code
        except Exception:
            logger.exception("Click %s failed", "prepare" if expected_action == 0 else "complete")
            code = ClickError.FAILED_TO_UPDATE
        response.update(error=int(code), error_note=ERROR_NOTES[code])
        logger.info(
            "Click action=%s click_trans_id=%s order=%s -> %s",
            expected_action,
            params.get("click_trans_id"),
            params.get("merchant_trans_id"),
            int(code),
        )
        return response

    def _validate_request(self, params: dict, expected_action: int) -> None:
        required = PREPARE_FIELDS if expected_action == ACTION_PREPARE else COMPLETE_FIELDS
        for field in required:
            value = params.get(field)
            if value is None or (value == "" and field != "error_note"):
                raise _Reject(ClickError.BAD_REQUEST)
        try:
            action = int(params["action"])
        except (TypeError, ValueError):
            raise _Reject(ClickError.ACTION_NOT_FOUND) from None
        if action not in (ACTION_PREPARE, ACTION_COMPLETE):
            raise _Reject(ClickError.ACTION_NOT_FOUND)
        expected = build_sign(params, self.secret_key, action)
        if not hmac.compare_digest(expected, str(params["sign_string"]).lower()):
            raise _Reject(ClickError.SIGN_CHECK_FAILED)
        if action != expected_action:
            raise _Reject(ClickError.ACTION_NOT_FOUND)
        if str(params["service_id"]) != self.service_id:
            raise _Reject(ClickError.BAD_REQUEST)

    @staticmethod
    def _amount(params: dict) -> Decimal:
        try:
            amount = Decimal(str(params["amount"]))
        except InvalidOperation:
            raise _Reject(ClickError.INVALID_AMOUNT) from None
        if not amount.is_finite() or amount <= 0:
            raise _Reject(ClickError.INVALID_AMOUNT)
        return amount.quantize(Decimal("0.01"))

    @staticmethod
    def _lock_order(params: dict) -> Order:
        try:
            return Order.objects.select_for_update().get(pk=int(params["merchant_trans_id"]))
        except (Order.DoesNotExist, ValueError):
            raise _Reject(ClickError.USER_NOT_FOUND) from None

    @staticmethod
    def _check_order_payable(order: Order) -> None:
        if order.status == Order.Status.CANCELLED:
            raise _Reject(ClickError.TRANSACTION_CANCELLED)
        if not order.is_payable:
            raise _Reject(ClickError.ALREADY_PAID)

    @transaction.atomic
    def _prepare(self, params: dict) -> int:
        amount = self._amount(params)
        order = self._lock_order(params)

        existing = Payment.objects.filter(
            provider=self.name, external_id=str(params["click_trans_id"])
        ).first()
        if existing is not None:
            # Click retried Prepare: answer with the same id (idempotent).
            if existing.order_id != order.pk:
                raise _Reject(ClickError.TRANSACTION_NOT_FOUND)
            if existing.state == Payment.State.PERFORMED:
                raise _Reject(ClickError.ALREADY_PAID)
            if existing.state < 0:
                raise _Reject(ClickError.TRANSACTION_CANCELLED)
            return existing.pk

        self._check_order_payable(order)
        if amount != order.total_amount:
            raise _Reject(ClickError.INVALID_AMOUNT)

        payment = Payment.objects.create(
            provider=self.name,
            external_id=str(params["click_trans_id"]),
            order=order,
            amount=amount,
            extra={"click_paydoc_id": str(params["click_paydoc_id"])},
        )
        return payment.pk

    @transaction.atomic
    def _complete(self, params: dict) -> tuple[ClickError, int]:
        amount = self._amount(params)
        order = self._lock_order(params)
        try:
            payment = Payment.objects.select_for_update().get(
                pk=int(params["merchant_prepare_id"]),
                provider=self.name,
                external_id=str(params["click_trans_id"]),
                order=order,
            )
        except (Payment.DoesNotExist, ValueError):
            raise _Reject(ClickError.TRANSACTION_NOT_FOUND) from None

        if payment.state == Payment.State.PERFORMED:
            raise _Reject(ClickError.ALREADY_PAID)
        if payment.state < 0:
            raise _Reject(ClickError.TRANSACTION_CANCELLED)

        try:
            click_error = int(params["error"])
        except ValueError:
            raise _Reject(ClickError.BAD_REQUEST) from None
        if click_error < 0:
            # Click could not charge the customer: cancel our side as well.
            payment.state = Payment.State.CANCELLED
            payment.reason = click_error
            payment.cancelled_at = timezone.now()
            payment.save(update_fields=["state", "reason", "cancelled_at", "updated_at"])
            # Return (not raise) so the cancellation is committed.
            return ClickError.TRANSACTION_CANCELLED, payment.pk

        if amount != payment.amount:
            raise _Reject(ClickError.INVALID_AMOUNT)
        self._check_order_payable(order)

        payment.state = Payment.State.PERFORMED
        payment.performed_at = timezone.now()
        payment.save(update_fields=["state", "performed_at", "updated_at"])
        services.mark_order_paid(order)
        return ClickError.SUCCESS, payment.pk
