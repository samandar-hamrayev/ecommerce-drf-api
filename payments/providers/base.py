from abc import ABC, abstractmethod
from decimal import Decimal

from orders.models import Order


class PaymentProvider(ABC):
    """Common interface every payment provider implements.

    A provider knows how to (1) send the customer to its hosted checkout and
    (2) process its own server-to-server callbacks. Order state changes are
    delegated to :mod:`payments.services` so providers never touch the order
    state machine directly.
    """

    name: str

    @abstractmethod
    def is_configured(self) -> bool:
        """True when all credentials required by this provider are set."""

    @abstractmethod
    def build_checkout_url(self, order: Order, return_url: str = "") -> str:
        """URL of the provider's hosted payment page for ``order``."""

    @staticmethod
    def to_tiyin(amount: Decimal) -> int:
        return int((amount * 100).to_integral_value())
