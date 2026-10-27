"""Input hardening: control characters, non-ASCII digits, body size, request IDs,
response headers, and Markdown escaping in the UI."""

import uuid

import pytest
from fastapi.testclient import TestClient

from app.api.routes import get_service
from app.config import MAX_BODY_BYTES
from app.domain import phone, text
from app.main import create_app
from tests.unit.fakes import FakeLedgerService
from ui.markdown_safe import escape


@pytest.fixture
def client():
    app = create_app()
    service = FakeLedgerService()
    app.dependency_overrides[get_service] = lambda: service
    return TestClient(app, raise_server_exceptions=False)


def new_account(client) -> str:
    return client.post("/accounts", json={"name": "Vidwan Gowda", "phone": "9000000001"}).json()["id"]


# --- control characters (item 4) ---------------------------------------------------


@pytest.mark.parametrize("bad", ["a\x00b", "line\nbreak", "tab\there", "bell\x07", "del\x7f"])
def test_text_with_control_characters_is_rejected(bad):
    with pytest.raises(ValueError):
        text.clean(bad)


@pytest.mark.parametrize("good", ["Vidwan Gowda", "ವಿದ್ವಾನ್ ಗೌಡ", "José", "O'Brien-Smith", "क्‍ष"])
def test_real_names_in_any_script_are_accepted(good):
    assert text.clean(good)


def test_text_is_nfc_normalised():
    # "é" as one code point vs "e" + combining accent: same text, same idempotency key.
    assert text.clean("José") == text.clean("José")


@pytest.mark.parametrize("field", ["name", "description", "reference_id"])
def test_control_characters_are_400_not_500(client, field):
    if field == "name":
        res = client.post("/accounts", json={"name": "a\x00b", "phone": "9000000002"})
    else:
        body = {"type": "credit", "amount": "1.00", "description": "d", "reference_id": "r", field: "a\x00b"}
        res = client.post(f"/accounts/{new_account(client)}/transactions", json=body)
    assert res.status_code == 400
    assert res.json()["error"]["code"] == "VALIDATION_ERROR"


# --- phone digits (item 5) ---------------------------------------------------------


def in_script(digits: str, zero: int) -> str:
    """The same number written with another script's digit characters."""
    return "".join(chr(zero + int(d)) for d in digits)


FULL_WIDTH = in_script("9000000001", 0xFF10)
ARABIC_INDIC = in_script("9000000001", 0x0660)


@pytest.mark.parametrize("bad", [FULL_WIDTH, ARABIC_INDIC, "9000000001\t", "9000000001\n"])
def test_phone_accepts_only_ascii_digits(bad):
    with pytest.raises(ValueError):
        phone.normalize(bad)


def test_non_ascii_digit_phone_is_400(client):
    res = client.post("/accounts", json={"name": "x", "phone": FULL_WIDTH})
    assert res.status_code == 400


# --- body size (item 6) ------------------------------------------------------------


def test_oversized_body_is_413(client):
    res = client.post("/accounts", json={"name": "x" * (MAX_BODY_BYTES + 1), "phone": "9000000001"})
    assert res.status_code == 413
    assert res.json()["error"]["code"] == "PAYLOAD_TOO_LARGE"


def test_oversized_chunked_body_is_413(client):
    def chunks():
        yield b'{"name": "'
        for _ in range(MAX_BODY_BYTES // 1000 + 2):
            yield b"x" * 1000
        yield b'", "phone": "9000000001"}'

    res = client.post("/accounts", content=chunks(), headers={"Content-Type": "application/json"})
    assert res.status_code == 413
    assert res.json()["error"]["code"] == "PAYLOAD_TOO_LARGE"


def test_normal_body_is_unaffected(client):
    assert client.post("/accounts", json={"name": "x" * 100, "phone": "9000000001"}).status_code == 201


# --- request IDs and headers (item 8) ----------------------------------------------


@pytest.mark.parametrize("supplied", ["x" * 65, "has space", "semi;colon", "<script>", "ünïcode"])
def test_unsafe_request_id_is_replaced(client, supplied):
    res = client.get(f"/accounts/{uuid.uuid4()}", headers={"X-Request-ID": supplied.encode("utf-8")})
    echoed = res.headers["X-Request-ID"]
    assert echoed != supplied
    assert len(echoed) == 32


@pytest.mark.parametrize("supplied", ["trace-123", "a.b_c-D", "x" * 64])
def test_safe_request_id_is_kept(client, supplied):
    res = client.get(f"/accounts/{uuid.uuid4()}", headers={"X-Request-ID": supplied})
    assert res.headers["X-Request-ID"] == supplied


def test_responses_are_not_cacheable(client):
    res = client.get(f"/accounts/{new_account(client)}")
    assert res.headers["Cache-Control"] == "no-store"
    assert res.headers["X-Content-Type-Options"] == "nosniff"


# --- UI Markdown escaping (item 10) ------------------------------------------------


@pytest.mark.parametrize(
    "name",
    ["[Click here](https://example.com)", "# Heading", "**bold**", ":rocket:", "![img](x.png)", "`code`", "$x^2$"],
)
def test_markdown_in_names_is_neutralised(name):
    escaped = escape(name)
    # Every Markdown control character is preceded by a backslash.
    for i, ch in enumerate(escaped):
        if ch in "[]()#*:!`$" and (i == 0 or escaped[i - 1] != "\\"):
            pytest.fail(f"unescaped {ch!r} in {escaped!r}")


def test_plain_names_read_the_same():
    assert escape("Vidwan Gowda") == "Vidwan Gowda"
