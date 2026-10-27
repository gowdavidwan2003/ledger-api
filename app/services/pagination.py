"""Opaque cursors for keyset pagination. Clients treat them as strings."""

import base64
import binascii
from datetime import datetime
from uuid import UUID

from app.domain.errors import InvalidCursor


def encode(created_at: datetime, row_id: UUID) -> str:
    return base64.urlsafe_b64encode(f"{created_at.isoformat()}|{row_id}".encode()).decode()


def decode(cursor: str) -> tuple[datetime, UUID]:
    try:
        created_at, row_id = base64.urlsafe_b64decode(cursor.encode()).decode().split("|")
        return datetime.fromisoformat(created_at), UUID(row_id)
    except (ValueError, binascii.Error, UnicodeDecodeError):
        raise InvalidCursor() from None
