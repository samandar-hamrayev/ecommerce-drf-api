import secrets
from datetime import timedelta

from django.utils import timezone

VERIFICATION_CODE_TTL = timedelta(minutes=10)


def generate_verification_code() -> str:
    """Return a cryptographically random 6-digit code."""
    return f"{secrets.randbelow(900_000) + 100_000}"


def get_expiry_time():
    return timezone.now() + VERIFICATION_CODE_TTL
