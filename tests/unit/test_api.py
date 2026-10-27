"""HTTP contract tests: validation, status codes, headers, error envelope.
Runs against FakeLedgerService, so no database is needed."""

import uuid

import psycopg
import pytest
from fastapi.testclient import TestClient

from app.api.routes import get_service
from app.main import create_app
from tests.unit.fakes import FakeLedgerService


@pytest.fixture
def service():
    return FakeLedgerService()


@pytest.fixture
def client(service):
    app = create_app()
    app.dependency_overrides[get_service] = lambda: service
    # Not used as a context manager, so the lifespan (DB pool) never starts.
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def account_id(client):
    return client.post("/accounts", json={"name": "Vidwan Gowda", "phone": "9000000001"}).json()["id"]


def post(client, account_id, **overrides):
    body = {"type": "credit", "amount": "10.00", "description": "d", "reference_id": uuid.uuid4().hex, **overrides}
    return client.post(f"/accounts/{account_id}/transactions", json=body)


# --- accounts ---------------------------------------------------------------------


def test_create_account_shape(client):
    res = client.post("/accounts", json={"name": "  Vidwan Gowda ", "phone": "+91 90000 00001"})
    assert res.status_code == 201
    body = res.json()
    assert body["name"] == "Vidwan Gowda"
    assert body["balance"] == "0.00"
    assert body["phone"] == "+91 ******0001"
    assert set(body) == {"id", "name", "phone", "balance", "created_at"}


@pytest.mark.parametrize(
    "payload",
    [
        {"phone": "9000000001"},
        {"name": "", "phone": "9000000001"},
        {"name": "   ", "phone": "9000000001"},
        {"name": "x" * 101, "phone": "9000000001"},
        {"name": 5, "phone": "9000000001"},
        {"name": "No Phone"},
        {"name": "Bad Phone", "phone": "12345"},
        {"name": "Bad Phone", "phone": "5000000001"},
        None,
    ],
)
def test_bad_account_payload_is_400(client, payload):
    res = client.post("/accounts", json=payload)
    assert res.status_code == 400
    assert res.json()["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.parametrize("field", ["balance", "id", "created_at"])
def test_client_cannot_set_system_fields(client, field):
    res = client.post("/accounts", json={"name": "Sneaky", "phone": "9000000002", field: "1"})
    assert res.status_code == 400
    assert res.json()["error"]["details"][0]["field"] == field


def test_duplicate_phone_is_409_in_any_format(client, account_id):
    res = client.post("/accounts", json={"name": "Someone Else", "phone": "+91-90000-00001"})
    assert res.status_code == 409
    assert res.json()["error"]["code"] == "PHONE_ALREADY_REGISTERED"


@pytest.mark.parametrize("typed", ["9000000001", "+91 90000 00001", "09000000001"])
def test_lookup_by_phone(client, account_id, typed):
    res = client.post("/accounts/lookup", json={"phone": typed})
    assert res.status_code == 200
    assert res.json()["id"] == account_id


def test_lookup_unknown_phone_is_404(client):
    res = client.post("/accounts/lookup", json={"phone": "9999999999"})
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "PHONE_NOT_REGISTERED"


def test_lookup_invalid_phone_is_400(client):
    assert client.post("/accounts/lookup", json={"phone": "abc"}).status_code == 400


def test_full_phone_number_never_returned(client, account_id):
    for res in (client.get(f"/accounts/{account_id}"), client.post("/accounts/lookup", json={"phone": "9000000001"})):
        assert "9000000001" not in res.text


def test_balance_endpoint(client, account_id):
    post(client, account_id, amount="12.34")
    assert client.get(f"/accounts/{account_id}/balance").json() == {"account_id": account_id, "balance": "12.34"}


@pytest.mark.parametrize("path", ["/accounts/{id}", "/accounts/{id}/balance", "/accounts/{id}/transactions"])
def test_unknown_account_is_404(client, path):
    res = client.get(path.format(id=uuid.uuid4()))
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "ACCOUNT_NOT_FOUND"


def test_malformed_uuid_is_400(client):
    assert client.get("/accounts/not-a-uuid").status_code == 400


# --- transactions -----------------------------------------------------------------


@pytest.mark.parametrize(
    "overrides",
    [
        {"type": "refund"},
        {"amount": 0},
        {"amount": -5},
        {"amount": "10.001"},
        {"amount": "abc"},
        {"amount": True},
        {"amount": 1_000_000_001},
        {"description": ""},
        {"description": "x" * 256},
        {"reference_id": " "},
        {"reference_id": "x" * 101},
        {"balance_after": "1.00"},
    ],
)
def test_transaction_validation(client, account_id, overrides):
    res = post(client, account_id, **overrides)
    assert res.status_code == 400, res.text
    assert res.json()["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.parametrize("missing", ["type", "amount", "description", "reference_id"])
def test_required_fields(client, account_id, missing):
    body = {"type": "credit", "amount": 1, "description": "d", "reference_id": "r"}
    del body[missing]
    assert client.post(f"/accounts/{account_id}/transactions", json=body).status_code == 400


def test_amount_accepts_number_or_string(client, account_id):
    assert post(client, account_id, amount=10).json()["amount"] == "10.00"
    assert post(client, account_id, amount=10.5).json()["amount"] == "10.50"
    assert post(client, account_id, amount="0.01").json()["amount"] == "0.01"


def test_insufficient_funds_is_422_with_details(client, account_id):
    post(client, account_id, amount="50.00")
    res = post(client, account_id, type="debit", amount="100.00")
    assert res.status_code == 422
    assert res.json()["error"] == {
        "code": "INSUFFICIENT_FUNDS",
        "message": "Debit rejected: balance is lower than the amount",
        "details": {"balance": "50.00", "requested": "100.00"},
    }


def test_replay_is_200_with_header(client, account_id):
    first = post(client, account_id, reference_id="r1")
    second = post(client, account_id, reference_id="r1")
    assert (first.status_code, second.status_code) == (201, 200)
    assert second.headers["Idempotent-Replayed"] == "true"
    assert "Idempotent-Replayed" not in first.headers
    assert second.json() == first.json()


def test_conflicting_reference_is_409(client, account_id):
    first = post(client, account_id, reference_id="r1", amount="1.00")
    res = post(client, account_id, reference_id="r1", amount="2.00")
    assert res.status_code == 409
    assert res.json()["error"]["details"] == {"existing_transaction_id": first.json()["id"]}


def test_bad_cursor_is_400(client, account_id):
    res = client.get(f"/accounts/{account_id}/transactions", params={"cursor": "garbage"})
    assert (res.status_code, res.json()["error"]["code"]) == (400, "INVALID_CURSOR")


@pytest.mark.parametrize("limit", [0, 101, "x"])
def test_bad_limit_is_400(client, account_id, limit):
    assert client.get(f"/accounts/{account_id}/transactions", params={"limit": limit}).status_code == 400


# --- cross-cutting ----------------------------------------------------------------


def test_request_id_is_generated_and_echoed(client):
    generated = client.get(f"/accounts/{uuid.uuid4()}").headers["X-Request-ID"]
    assert len(generated) == 32
    echoed = client.get(f"/accounts/{uuid.uuid4()}", headers={"X-Request-ID": "trace-123"})
    assert echoed.headers["X-Request-ID"] == "trace-123"


def test_unknown_route_uses_error_envelope(client):
    res = client.get("/nope")
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "NOT_FOUND"


def test_database_outage_is_503(client, service, monkeypatch):
    def down(*_):
        raise psycopg.OperationalError("connection refused")

    monkeypatch.setattr(service, "create_account", down)
    res = client.post("/accounts", json={"name": "x", "phone": "9000000003"})
    assert res.status_code == 503
    assert res.json()["error"]["code"] == "DATABASE_UNAVAILABLE"


def test_unexpected_error_is_500_without_leaking(client, service, monkeypatch):
    def boom(*_):
        raise RuntimeError("secret internal detail")

    monkeypatch.setattr(service, "create_account", boom)
    res = client.post("/accounts", json={"name": "x", "phone": "9000000003"})
    assert res.status_code == 500
    assert "secret" not in res.text


def test_openapi_documents_error_responses(client):
    spec = client.get("/openapi.json").json()
    responses = spec["paths"]["/accounts/{account_id}/transactions"]["post"]["responses"]
    assert {"200", "201", "404", "409", "422"} <= set(responses)
