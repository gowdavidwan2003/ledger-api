"""Parallel requests against one account: the row lock must serialise them."""

import asyncio
import time

import httpx

from tests.integration.conftest import new_account, txn


async def _fire(app, requests: list[tuple[str, dict]]) -> list[httpx.Response]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test", timeout=60) as ac:
        return await asyncio.gather(*(ac.post(path, json=body) for path, body in requests))


def test_parallel_debits_never_overdraw(client, account):
    path = f"/accounts/{account['id']}/transactions"
    client.post(path, json=txn("credit", 100))

    # 20 debits of 10 against 100: exactly 10 may succeed, whatever the interleaving.
    results = asyncio.run(_fire(client.app, [(path, txn("debit", 10)) for _ in range(20)]))
    codes = [r.status_code for r in results]

    assert codes.count(201) == 10
    assert codes.count(422) == 10
    assert client.get(f"/accounts/{account['id']}/balance").json()["balance"] == "0.00"


def test_parallel_retries_of_one_reference_apply_once(client, account):
    path = f"/accounts/{account['id']}/transactions"
    payload = txn("credit", 25, reference_id="double-click")
    results = asyncio.run(_fire(client.app, [(path, payload)] * 10))

    assert sorted(r.status_code for r in results) == [200] * 9 + [201]
    assert len({r.json()["id"] for r in results}) == 1
    assert client.get(f"/accounts/{account['id']}/balance").json()["balance"] == "25.00"


def test_mixed_parallel_credits_and_debits_balance_correctly(client, account):
    path = f"/accounts/{account['id']}/transactions"
    client.post(path, json=txn("credit", 50))
    # 10 credits of 5 and 10 debits of 5 in any order: balance stays >= 0 throughout
    # (enforced) and every accepted request is reflected in the final balance.
    reqs = [(path, txn("credit", 5)) for _ in range(10)] + [(path, txn("debit", 5)) for _ in range(10)]
    results = asyncio.run(_fire(client.app, reqs))

    accepted = [r.json() for r in results if r.status_code == 201]
    expected = 5000 + sum(500 if t["type"] == "credit" else -500 for t in accepted)
    assert client.get(f"/accounts/{account['id']}/balance").json()["balance"] == f"{expected / 100:.2f}"


def test_locks_are_per_account(client):
    """Load on one account must not block another: the lock is the account row."""
    busy = new_account(client, "busy")["id"]
    quiet = new_account(client, "quiet")["id"]
    reqs = [(f"/accounts/{busy}/transactions", txn("credit", 1)) for _ in range(15)]
    reqs.append((f"/accounts/{quiet}/transactions", txn("credit", 1)))

    start = time.perf_counter()
    results = asyncio.run(_fire(client.app, reqs))
    assert all(r.status_code == 201 for r in results)
    assert time.perf_counter() - start < 30
    assert client.get(f"/accounts/{busy}/balance").json()["balance"] == "15.00"
    assert client.get(f"/accounts/{quiet}/balance").json()["balance"] == "1.00"
