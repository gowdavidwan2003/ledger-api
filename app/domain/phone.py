"""Indian mobile numbers, normalised to E.164 (+91XXXXXXXXXX) so "98765 43210",
"+91-98765-43210" and "098765 43210" are the same account.

Only ASCII digits count. Python's \\d also matches other scripts' digits (e.g.
full-width U+FF10-U+FF19), which would pass here and then fail the database's
[0-9] check as a 500.
"""

import re

# fullmatch, not ^...$: "$" also matches just before a trailing "\n".
_ALLOWED = re.compile(r"[0-9 +\-()]*")
_MOBILE = re.compile(r"[6-9][0-9]{9}")


def normalize(raw: str) -> str:
    if not _ALLOWED.fullmatch(raw):
        raise ValueError("must be a 10-digit Indian mobile number starting with 6-9")
    digits = re.sub(r"[^0-9]", "", raw)
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    elif len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    if not _MOBILE.fullmatch(digits):
        raise ValueError("must be a 10-digit Indian mobile number starting with 6-9")
    return f"+91{digits}"


def mask(phone: str) -> str:
    """+919876543210 -> +91 ******3210. Responses never carry the full number."""
    return f"{phone[:3]} ******{phone[-4:]}"
