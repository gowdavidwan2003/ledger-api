"""Amounts travel as 2-decimal strings at the API edge and as integer minor units
(paise) everywhere else. Floats never touch a balance."""

from decimal import Decimal

MINOR_UNITS = 100
MAX_AMOUNT = Decimal("1000000000")  # per transaction, in major units


def to_minor(amount: Decimal) -> int:
    scaled = amount * MINOR_UNITS
    if scaled != scaled.to_integral_value():
        raise ValueError("amount has more than 2 decimal places")
    return int(scaled)


def to_major(minor: int) -> str:
    sign = "-" if minor < 0 else ""
    minor = abs(minor)
    return f"{sign}{minor // MINOR_UNITS}.{minor % MINOR_UNITS:02d}"
