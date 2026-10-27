"""The database's own guarantees, tested by bypassing the application entirely.
If a future bug (or a manual SQL session) tries to break the ledger, these hold."""

import uuid

import psycopg
import pytest

from scripts.migrate import migrate
from tests.integration.conftest import DATABASE_URL, TEST_SCHEMA, new_account, txn


def test_balance_can_never_go_negative(pool, account):
    with pool.connection() as conn, pytest.raises(psycopg.errors.CheckViolation):
        conn.execute("update accounts set balance = -1 where id = %s", (account["id"],))


def test_reference_unique_per_account(client, pool, account):
    client.post(f"/accounts/{account['id']}/transactions", json=txn("credit", 1, reference_id="dup"))
    with pool.connection() as conn, pytest.raises(psycopg.errors.UniqueViolation):
        conn.execute(
            "insert into transactions (account_id, type, amount, description, reference_id, balance_after)"
            " values (%s, 'credit', 100, 'x', 'dup', 100)",
            (account["id"],),
        )


@pytest.mark.parametrize("statement", ["update transactions set amount = 1", "delete from transactions"])
def test_transactions_are_append_only_even_for_the_owner(client, owner, account, statement):
    client.post(f"/accounts/{account['id']}/transactions", json=txn("credit", 10))
    with pytest.raises(psycopg.errors.RestrictViolation):
        owner.execute(f"{statement} where account_id = %s", (account["id"],))


@pytest.mark.parametrize("table", ["transactions", "accounts"])
def test_truncate_is_blocked_even_for_the_owner(owner, table):
    with pytest.raises(psycopg.errors.RestrictViolation):
        owner.execute(f"truncate {table} cascade")


def test_zero_or_negative_amount_rejected(pool, account):
    with pool.connection() as conn, pytest.raises(psycopg.errors.CheckViolation):
        conn.execute(
            "insert into transactions (account_id, type, amount, description, reference_id, balance_after)"
            " values (%s, 'credit', 0, 'x', %s, 0)",
            (account["id"], uuid.uuid4().hex),
        )


@pytest.mark.parametrize("bad_phone", ["9876543210", "+915876543210", "+91987654321"])
def test_phone_must_be_stored_normalised(pool, bad_phone):
    with pool.connection() as conn, pytest.raises(psycopg.errors.CheckViolation):
        conn.execute("insert into accounts (name, phone) values ('x', %s)", (bad_phone,))


def test_ids_are_time_ordered_uuid_v7(client):
    ids = [uuid.UUID(new_account(client, "v7")["id"]) for _ in range(3)]
    assert all(i.version == 7 for i in ids)
    assert ids == sorted(ids)


def test_migrations_are_rerunnable(client):
    assert migrate(DATABASE_URL, TEST_SCHEMA) == []
