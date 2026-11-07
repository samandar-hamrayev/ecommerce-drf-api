"""Payme (Paycom) Merchant API - JSON-RPC 2.0 endpoint.

Payme calls one merchant URL with ``{"id", "method", "params"}`` bodies and an
``Authorization: Basic base64("Paycom:<KEY>")`` header. Amounts are in tiyin
(1 UZS = 100 tiyin) and all timestamps are milliseconds since the epoch.

Transaction states: 1 created, 2 performed, -1 cancelled before perform,
-2 cancelled after perform (refund). A created transaction expires after
12 hours (``TRANSACTION_TIMEOUT_MS``) and is then cancelled with reason 4.
"""

import base64
import binascii
import hmac
import json
import logging
from datetime import datetime

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from orders.models import Order
from payments import services
from payments.models import Payment

from .base import PaymentProvider

logger = logging.getLogger(__name__)

TRANSACTION_TIMEOUT_MS = 43_200_000  # 12 hours
REASON_TIMEOUT = 4
AUTH_LOGIN = "Paycom"


class PaymeError(Exception):
    """Raised inside a method handler; rendered as a JSON-RPC ``error``."""

    def __init__(self, code: int, message: dict[str, str], data: str | None = None):
        super().__init__(code)
        self.code = code
        self.message = message
        self.data = data

    def as_dict(self) -> dict:
        error = {"code": self.code, "message": self.message}
        if self.data is not None:
            error["data"] = self.data
        return error


def _msg(ru: str, uz: str, en: str) -> dict[str, str]:
    return {"ru": ru, "uz": uz, "en": en}


# --- protocol errors ---------------------------------------------------------
def err_parse():
    return PaymeError(-32700, _msg("Ошибка разбора JSON", "JSON xatosi", "Parse error"))


def err_invalid_request(data=None):
    return PaymeError(
        -32600, _msg("Неверный RPC-запрос", "Noto'g'ri RPC so'rov", "Invalid RPC request"), data
    )


def err_method_not_found(method):
    return PaymeError(
        -32601, _msg("Метод не найден", "Metod topilmadi", "Method not found"), str(method)
    )


def err_insufficient_privilege():
    return PaymeError(
        -32504,
        _msg("Недостаточно привилегий", "Ruxsat yetarli emas", "Insufficient privilege"),
    )


def err_system():
    return PaymeError(-32400, _msg("Системная ошибка", "Tizim xatosi", "System error"))


# --- business errors ---------------------------------------------------------
def err_invalid_amount():
    return PaymeError(-31001, _msg("Неверная сумма", "Noto'g'ri summa", "Invalid amount"))


def err_transaction_not_found():
    return PaymeError(
        -31003, _msg("Транзакция не найдена", "Tranzaksiya topilmadi", "Transaction not found")
    )


def err_cannot_cancel():
    return PaymeError(
        -31007,
        _msg(
            "Заказ выполнен, отмена невозможна",
            "Buyurtma bajarilgan, bekor qilib bo'lmaydi",
            "Order is fulfilled, transaction cannot be cancelled",
        ),
    )


def err_cannot_perform():
    return PaymeError(
        -31008,
        _msg(
            "Невозможно выполнить операцию",
            "Amalni bajarib bo'lmaydi",
            "Unable to perform operation",
        ),
    )


def err_order_not_found(field):
    return PaymeError(
        -31050, _msg("Заказ не найден", "Buyurtma topilmadi", "Order not found"), field
    )


def err_order_unavailable(field):
    # -31050..-31099 are reserved for merchant-defined ``account`` errors.
    return PaymeError(
        -31051,
        _msg(
            "Заказ недоступен для оплаты",
            "Buyurtmani to'lab bo'lmaydi",
            "Order is not available for payment",
        ),
        field,
    )


def to_ms(dt: datetime | None) -> int:
    return int(dt.timestamp() * 1000) if dt else 0


def now_ms() -> int:
    return to_ms(timezone.now())


class PaymeProvider(PaymentProvider):
    name = Payment.Provider.PAYME

    def __init__(self):
        self.merchant_id = settings.PAYME_MERCHANT_ID
        self.key = settings.PAYME_KEY
        self.account_field = settings.PAYME_ACCOUNT_FIELD
        self.checkout_base = settings.PAYME_CHECKOUT_URL.rstrip("/")
        self.methods = {
            "CheckPerformTransaction": self.check_perform_transaction,
            "CreateTransaction": self.create_transaction,
            "PerformTransaction": self.perform_transaction,
            "CancelTransaction": self.cancel_transaction,
            "CheckTransaction": self.check_transaction,
            "GetStatement": self.get_statement,
        }

    # ------------------------------------------------------------------ checkout
    def is_configured(self) -> bool:
        return bool(self.merchant_id and self.key)

    def build_checkout_url(self, order: Order, return_url: str = "") -> str:
        parts = [
            f"m={self.merchant_id}",
            f"ac.{self.account_field}={order.pk}",
            f"a={self.to_tiyin(order.total_amount)}",
        ]
        if return_url:
            parts.append(f"c={return_url}")
        token = base64.b64encode(";".join(parts).encode()).decode()
        return f"{self.checkout_base}/{token}"

    # ------------------------------------------------------------- entry point
    def handle(self, raw_body: bytes, authorization: str | None) -> dict:
        """Process one JSON-RPC call and return the response body."""
        request_id = None
        try:
            self._authenticate(authorization)
            try:
                payload = json.loads(raw_body)
            except (ValueError, UnicodeDecodeError):
                raise err_parse() from None
            if not isinstance(payload, dict):
                raise err_invalid_request()
            request_id = payload.get("id")
            method = payload.get("method")
            params = payload.get("params")
            if not isinstance(method, str) or not isinstance(params, dict):
                raise err_invalid_request()
            handler = self.methods.get(method)
            if handler is None:
                raise err_method_not_found(method)
            result = handler(params)
            logger.info("Payme %s id=%s -> ok", method, params.get("id"))
            return {"jsonrpc": "2.0", "id": request_id, "result": result}
        except PaymeError as error:
            logger.info("Payme error %s", error.code)
            return {"jsonrpc": "2.0", "id": request_id, "error": error.as_dict()}
        except Exception:
            logger.exception("Payme handler crashed")
            return {"jsonrpc": "2.0", "id": request_id, "error": err_system().as_dict()}

    def _authenticate(self, authorization: str | None) -> None:
        if not self.key or not authorization or not authorization.startswith("Basic "):
            raise err_insufficient_privilege()
        try:
            decoded = base64.b64decode(authorization[6:], validate=True).decode()
        except (binascii.Error, UnicodeDecodeError):
            raise err_insufficient_privilege() from None
        login, _, password = decoded.partition(":")
        if not (
            hmac.compare_digest(login.encode(), AUTH_LOGIN.encode())
            and hmac.compare_digest(password.encode(), self.key.encode())
        ):
            raise err_insufficient_privilege()

    # ------------------------------------------------------------- validation
    @staticmethod
    def _require(params: dict, name: str, kind: type | tuple[type, ...]):
        value = params.get(name)
        if not isinstance(value, kind) or isinstance(value, bool):
            raise err_invalid_request(name)
        return value

    def _order_for(self, params: dict, *, lock: bool = False) -> Order:
        amount = self._require(params, "amount", int)
        account = self._require(params, "account", dict)
        field = self.account_field
        try:
            order_id = int(account[field])
        except (KeyError, TypeError, ValueError):
            raise err_order_not_found(field) from None
        qs = Order.objects.select_for_update() if lock else Order.objects
        order = qs.filter(pk=order_id).first()
        if order is None:
            raise err_order_not_found(field)
        if not order.is_payable:
            raise err_order_unavailable(field)
        if amount != self.to_tiyin(order.total_amount):
            raise err_invalid_amount()
        return order

    def _get_transaction(self, params: dict) -> Payment:
        payme_id = self._require(params, "id", str)
        payment = (
            Payment.objects.select_for_update()
            .select_related("order")
            .filter(provider=self.name, external_id=payme_id)
            .first()
        )
        if payment is None:
            raise err_transaction_not_found()
        return payment

    @staticmethod
    def _is_expired(payment: Payment) -> bool:
        return now_ms() - to_ms(payment.created_at) > TRANSACTION_TIMEOUT_MS

    @staticmethod
    def _cancel(payment: Payment, state: int, reason: int | None) -> None:
        payment.state = state
        payment.reason = reason
        payment.cancelled_at = timezone.now()
        payment.save(update_fields=["state", "reason", "cancelled_at", "updated_at"])

    # ---------------------------------------------------------------- methods
    def check_perform_transaction(self, params: dict) -> dict:
        self._order_for(params)
        return {"allow": True}

    def create_transaction(self, params: dict) -> dict:
        payme_id = self._require(params, "id", str)
        payme_time = self._require(params, "time", int)

        # A cancelled-on-timeout transaction must stay cancelled even though
        # we then answer with an error, so the timeout path commits first.
        with transaction.atomic():
            payment = (
                Payment.objects.select_for_update()
                .filter(provider=self.name, external_id=payme_id)
                .first()
            )
            if payment is not None:
                if payment.state != Payment.State.CREATED:
                    raise err_cannot_perform()
                if self._is_expired(payment):
                    self._cancel(payment, Payment.State.CANCELLED, REASON_TIMEOUT)
                    expired = True
                else:
                    return self._create_result(payment)
            else:
                expired = False
        if expired:
            raise err_cannot_perform()

        with transaction.atomic():
            order = self._order_for(params, lock=True)
            # One order -> at most one live Payme transaction.
            if Payment.objects.filter(
                provider=self.name, order=order, state=Payment.State.CREATED
            ).exists():
                raise err_order_unavailable(self.account_field)
            if now_ms() - payme_time > TRANSACTION_TIMEOUT_MS:
                raise err_cannot_perform()
            payment = Payment.objects.create(
                provider=self.name,
                external_id=payme_id,
                order=order,
                amount=order.total_amount,
                provider_time=payme_time,
            )
        return self._create_result(payment)

    @staticmethod
    def _create_result(payment: Payment) -> dict:
        return {
            "create_time": to_ms(payment.created_at),
            "transaction": str(payment.pk),
            "state": payment.state,
        }

    def perform_transaction(self, params: dict) -> dict:
        with transaction.atomic():
            payment = self._get_transaction(params)
            if payment.state == Payment.State.CREATED:
                if self._is_expired(payment):
                    self._cancel(payment, Payment.State.CANCELLED, REASON_TIMEOUT)
                    expired = True
                else:
                    order = Order.objects.select_for_update().get(pk=payment.order_id)
                    if not order.is_payable:
                        raise err_cannot_perform()
                    payment.state = Payment.State.PERFORMED
                    payment.performed_at = timezone.now()
                    payment.save(update_fields=["state", "performed_at", "updated_at"])
                    services.mark_order_paid(order)
                    expired = False
            elif payment.state == Payment.State.PERFORMED:
                expired = False  # idempotent repeat
            else:
                raise err_cannot_perform()
        if expired:
            raise err_cannot_perform()
        return {
            "transaction": str(payment.pk),
            "perform_time": to_ms(payment.performed_at),
            "state": payment.state,
        }

    def cancel_transaction(self, params: dict) -> dict:
        reason = self._require(params, "reason", int)
        with transaction.atomic():
            payment = self._get_transaction(params)
            if payment.state == Payment.State.CREATED:
                self._cancel(payment, Payment.State.CANCELLED, reason)
            elif payment.state == Payment.State.PERFORMED:
                order = Order.objects.select_for_update().get(pk=payment.order_id)
                if order.status in (Order.Status.SHIPPED, Order.Status.DELIVERED):
                    raise err_cannot_cancel()
                self._cancel(payment, Payment.State.CANCELLED_AFTER_PERFORM, reason)
                services.refund_order(order)
            # Already cancelled: idempotent, return the stored result.
        return {
            "transaction": str(payment.pk),
            "cancel_time": to_ms(payment.cancelled_at),
            "state": payment.state,
        }

    def check_transaction(self, params: dict) -> dict:
        with transaction.atomic():
            payment = self._get_transaction(params)
        return {
            "create_time": to_ms(payment.created_at),
            "perform_time": to_ms(payment.performed_at),
            "cancel_time": to_ms(payment.cancelled_at),
            "transaction": str(payment.pk),
            "state": payment.state,
            "reason": payment.reason,
        }

    def get_statement(self, params: dict) -> dict:
        start = self._require(params, "from", int)
        end = self._require(params, "to", int)
        payments = Payment.objects.filter(
            provider=self.name, provider_time__gte=start, provider_time__lte=end
        ).order_by("provider_time")
        return {
            "transactions": [
                {
                    "id": p.external_id,
                    "time": p.provider_time,
                    "amount": self.to_tiyin(p.amount),
                    "account": {self.account_field: str(p.order_id)},
                    "create_time": to_ms(p.created_at),
                    "perform_time": to_ms(p.performed_at),
                    "cancel_time": to_ms(p.cancelled_at),
                    "transaction": str(p.pk),
                    "state": p.state,
                    "reason": p.reason,
                }
                for p in payments
            ]
        }
