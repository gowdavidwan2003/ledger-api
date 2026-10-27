import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.domain.errors import InvalidCursor
from app.domain.money import to_major, to_minor
from app.services import pagination


@pytest.mark.parametrize(
    ("amount", "minor"),
    [("0.01", 1), ("1", 100), ("150.00", 15000), ("30.25", 3025), ("0.1", 10), ("1000000000", 100000000000)],
)
def test_to_minor_is_exact(amount, minor):
    assert to_minor(Decimal(amount)) == minor


def test_to_minor_rejects_fractions_of_paise():
    with pytest.raises(ValueError):
        to_minor(Decimal("10.001"))


@pytest.mark.parametrize(
    ("minor", "text"), [(0, "0.00"), (1, "0.01"), (15000, "150.00"), (3025, "30.25"), (-150, "-1.50")]
)
def test_to_major_formats_two_places(minor, text):
    assert to_major(minor) == text


def test_floats_would_have_drifted():
    # The reason amounts are integers: three 0.1 credits must total exactly 0.30.
    assert 0.1 + 0.1 + 0.1 != 0.3
    assert to_major(sum(to_minor(Decimal("0.1")) for _ in range(3))) == "0.30"


def test_cursor_round_trips():
    ts, row_id = datetime(2026, 10, 27, 10, 0, 0, 123456, tzinfo=UTC), uuid.uuid4()
    assert pagination.decode(pagination.encode(ts, row_id)) == (ts, row_id)


@pytest.mark.parametrize("bad", ["garbage", "", "bm90LWEtY3Vyc29y", "!!!"])
def test_bad_cursor_raises(bad):
    with pytest.raises(InvalidCursor):
        pagination.decode(bad)
