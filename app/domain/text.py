"""Free-text fields (names, descriptions, references) must be printable text.

Control characters (including NUL, which Postgres can't store in text) are
rejected up front so they surface as a 400, not a database error. Text is
normalised to NFC so visually identical strings compare equal, which matters for
idempotency. Format characters (category Cf) are allowed: ZWJ/ZWNJ are needed to
spell names correctly in Kannada and other Indic scripts.
"""

import unicodedata

_FORBIDDEN = {"Cc", "Cs"}  # control characters, lone surrogates


def clean(value: str) -> str:
    if any(unicodedata.category(ch) in _FORBIDDEN for ch in value):
        raise ValueError("must not contain control characters")
    return unicodedata.normalize("NFC", value)
