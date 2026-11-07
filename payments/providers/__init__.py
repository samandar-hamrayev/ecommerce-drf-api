from .base import PaymentProvider
from .click import ClickProvider

PROVIDERS: dict[str, type[PaymentProvider]] = {
    ClickProvider.name: ClickProvider,
}


def get_provider(name: str) -> PaymentProvider:
    try:
        return PROVIDERS[name]()
    except KeyError:
        raise ValueError(f"Unknown payment provider: {name}") from None


__all__ = ["PROVIDERS", "ClickProvider", "PaymentProvider", "get_provider"]
