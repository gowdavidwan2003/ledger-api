"""The app runs as ledger_app (db/migrations/003). These tests pin down exactly
what that role can and can't do, so a grant added by mistake fails the build."""

import psycopg
import pytest

from tests.integration.conftest import txn


def test_app_connections_run_as_the_app_role(pool):
    with pool.connection() as conn:
        assert conn.execute("select current_user as u").fetchone()["u"] == "ledger_app"


def test_app_role_can_do_its_job(client, account):
    # The whole API works under the restricted role.
    assert client.post(f"/accounts/{account['id']}/transactions", json=txn("credit", 10)).status_code == 201
    assert client.post(f"/accounts/{account['id']}/transactions", json=txn("debit", 4)).status_code == 201
    assert client.get(f"/accounts/{account['id']}/transactions").status_code == 200


@pytest.mark.parametrize(
    "statement",
    [
        "update transactions set amount = 1",
        "delete from transactions",
        "truncate transactions",
        "delete from accounts",
        "update accounts set name = 'renamed'",
        "update accounts set phone = '+919999999999'",
        "alter table transactions disable trigger transactions_append_only",
        "drop table transactions",
        "create table scratch (id int)",
    ],
)
def test_app_role_cannot_do_anything_else(pool, statement):
    with pool.connection() as conn, pytest.raises(psycopg.errors.InsufficientPrivilege):
        conn.execute(statement)


def test_supabase_api_roles_have_no_access(owner):
    roles = [r[0] for r in owner.execute("select rolname from pg_roles where rolname in ('anon', 'authenticated')")]
    if not roles:
        pytest.skip("not a Supabase database")
    for role in roles:
        usage = owner.execute("select has_schema_privilege(%s, current_schema(), 'USAGE')", (role,)).fetchone()[0]
        assert usage is False, role


def test_waiting_on_a_held_lock_times_out_with_503(client, owner, account):
    """A transaction stuck holding an account's row lock must not hang other
    requests: they give up after lock_timeout and get a retryable 503."""
    with owner.transaction():
        owner.execute("select 1 from accounts where id = %s for update", (account["id"],))
        res = client.post(f"/accounts/{account['id']}/transactions", json=txn("credit", 1))
    assert res.status_code == 503
    assert res.json()["error"]["code"] == "DATABASE_UNAVAILABLE"
    # Nothing was applied, and the account works again once the lock is released.
    assert client.get(f"/accounts/{account['id']}/balance").json()["balance"] == "0.00"
    assert client.post(f"/accounts/{account['id']}/transactions", json=txn("credit", 1)).status_code == 201
