"""End-to-end behaviour through HTTP and a real database."""

import uuid

from tests.integration.conftest import new_account, txn


def balance(client, account_id) -> str:
    return client.get(f"/accounts/{account_id}/balance").json()["balance"]


def test_new_account_starts_at_zero_with_unique_ids(client):
    accounts = [new_account(client, f"user {i}") for i in range(5)]
    assert {a["balance"] for a in accounts} == {"0.00"}
    assert len({a["id"] for a in accounts}) == 5


def test_phone_signup_and_lookup(client):
    created = client.post("/accounts", json={"name": "Vidwan Gowda", "phone": "+91 70000 12345"})
    assert created.status_code == 201
    assert created.json()["phone"] == "+91 ******2345"

    found = client.post("/accounts/lookup", json={"phone": "07000012345"})
    assert found.json()["id"] == created.json()["id"]

    dup = client.post("/accounts", json={"name": "Someone", "phone": "7000012345"})
    assert (dup.status_code, dup.json()["error"]["code"]) == (409, "PHONE_ALREADY_REGISTERED")


def test_spec_example_credit(client, account):
    """Current balance 100, credit 50, new balance 150."""
    client.post(f"/accounts/{account['id']}/transactions", json=txn("credit", 100))
    res = client.post(f"/accounts/{account['id']}/transactions", json=txn("credit", 50))
    assert res.status_code == 201
    assert res.json()["balance_after"] == "150.00"
    assert balance(client, account["id"]) == "150.00"


def test_debit_and_exact_zero(client, account):
    client.post(f"/accounts/{account['id']}/transactions", json=txn("credit", 100))
    assert client.post(f"/accounts/{account['id']}/transactions", json=txn("debit", "30.25")).status_code == 201
    assert client.post(f"/accounts/{account['id']}/transactions", json=txn("debit", "69.75")).status_code == 201
    assert balance(client, account["id"]) == "0.00"


def test_overdraft_rejected_and_nothing_written(client, account):
    client.post(f"/accounts/{account['id']}/transactions", json=txn("credit", 50))
    res = client.post(f"/accounts/{account['id']}/transactions", json=txn("debit", 100))
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "INSUFFICIENT_FUNDS"
    assert balance(client, account["id"]) == "50.00"
    history = client.get(f"/accounts/{account['id']}/transactions").json()["data"]
    assert [t["type"] for t in history] == ["credit"]


def test_amounts_are_exact(client, account):
    for _ in range(3):
        client.post(f"/accounts/{account['id']}/transactions", json=txn("credit", 0.1))
    assert balance(client, account["id"]) == "0.30"


def test_unknown_account(client):
    res = client.post(f"/accounts/{uuid.uuid4()}/transactions", json=txn("credit", 10))
    assert res.status_code == 404


def test_idempotent_retry_applies_once(client, account):
    payload = txn("credit", 100, reference_id="salary-oct")
    first = client.post(f"/accounts/{account['id']}/transactions", json=payload)
    second = client.post(f"/accounts/{account['id']}/transactions", json=payload)
    assert (first.status_code, second.status_code) == (201, 200)
    assert second.json() == first.json()
    assert balance(client, account["id"]) == "100.00"


def test_reference_conflict(client, account):
    client.post(f"/accounts/{account['id']}/transactions", json=txn("credit", 100, reference_id="r-1"))
    res = client.post(f"/accounts/{account['id']}/transactions", json=txn("credit", 999, reference_id="r-1"))
    assert res.status_code == 409
    assert balance(client, account["id"]) == "100.00"


def test_reference_is_scoped_per_account(client):
    a = new_account(client, "A")["id"]
    b = new_account(client, "B")["id"]
    assert client.post(f"/accounts/{a}/transactions", json=txn("credit", 5, reference_id="shared")).status_code == 201
    assert client.post(f"/accounts/{b}/transactions", json=txn("credit", 5, reference_id="shared")).status_code == 201


def test_rejected_debit_does_not_consume_reference(client, account):
    payload = txn("debit", 100, reference_id="pay-1")
    assert client.post(f"/accounts/{account['id']}/transactions", json=payload).status_code == 422
    client.post(f"/accounts/{account['id']}/transactions", json=txn("credit", 100))
    assert client.post(f"/accounts/{account['id']}/transactions", json=payload).status_code == 201


def test_history_newest_first_and_paginates(client, account):
    for i in range(5):
        client.post(f"/accounts/{account['id']}/transactions", json=txn("credit", i + 1, description=f"t{i}"))

    seen, cursor = [], None
    while True:
        params = {"limit": 2, **({"cursor": cursor} if cursor else {})}
        page = client.get(f"/accounts/{account['id']}/transactions", params=params).json()
        seen += [t["description"] for t in page["data"]]
        if not (cursor := page["next_cursor"]):
            break
    assert seen == ["t4", "t3", "t2", "t1", "t0"]


def test_history_filter_by_type(client, account):
    client.post(f"/accounts/{account['id']}/transactions", json=txn("credit", 10))
    client.post(f"/accounts/{account['id']}/transactions", json=txn("debit", 3))
    data = client.get(f"/accounts/{account['id']}/transactions", params={"type": "debit"}).json()["data"]
    assert [t["type"] for t in data] == ["debit"]


def test_balance_always_equals_sum_of_ledger(client, account):
    for t, amt in [
        ("credit", "100.00"),
        ("debit", "20.50"),
        ("credit", "5.25"),
        ("debit", "84.75"),
        ("credit", "1.00"),
    ]:
        assert client.post(f"/accounts/{account['id']}/transactions", json=txn(t, amt)).status_code == 201
    data = client.get(f"/accounts/{account['id']}/transactions", params={"limit": 100}).json()["data"]
    total_paise = sum((1 if t["type"] == "credit" else -1) * round(float(t["amount"]) * 100) for t in data)
    assert balance(client, account["id"]) == f"{total_paise / 100:.2f}" == "1.00"
    # balance_after on the newest row matches the account too
    assert data[0]["balance_after"] == "1.00"
