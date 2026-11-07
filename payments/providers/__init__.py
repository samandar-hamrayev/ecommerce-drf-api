from .base import PaymentProvider
from .click import ClickProvider
from .payme import PaymeProvider

PROVIDERS: dict[str, type[PaymentProvider]] = {
    ClickProvider.name: ClickProvider,
    PaymeProvider.name: PaymeProvider,
}


def get_provider(name: str) -> PaymentProvider:
    try:
        return PROVIDERS[name]()
    except KeyError:
        raise ValueError(f"Unknown payment provider: {name}") from None


__all__ = ["PROVIDERS", "ClickProvider", "PaymeProvider", "PaymentProvider", "get_provider"]
