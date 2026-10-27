import pytest

from app.domain.phone import mask, normalize


@pytest.mark.parametrize(
    "raw",
    [
        "9876543210",
        "98765 43210",
        "+91 98765 43210",
        "+91-98765-43210",
        "919876543210",
        "09876543210",
        "(987) 654-3210",
    ],
)
def test_formats_normalise_to_the_same_number(raw):
    assert normalize(raw) == "+919876543210"


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "12345",
        "5876543210",  # Indian mobiles start with 6-9
        "98765432100",  # 11 digits without a leading 0
        "+1 415 555 0100",
        "98765abc43210",
        "9876543210; drop table",
    ],
)
def test_invalid_numbers_are_rejected(raw):
    with pytest.raises(ValueError):
        normalize(raw)


def test_mask_shows_only_last_four_digits():
    assert mask("+919000000001") == "+91 ******0001"
