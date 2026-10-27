"""Integration tests run against a real Postgres. They rebuild an isolated schema
(default `ledger_test`) from the migrations on every run, so the app's `ledger`
schema is never touched. Skipped when DATABASE_URL is not set."""

import os
import random
import uuid

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg import sql

from app.config import Settings
from app.main import create_app
from scripts.migrate import migrate

DATABASE_URL = os.getenv("DATABASE_URL")
TEST_SCHEMA = os.getenv("TEST_DB_SCHEMA", "ledger_test")


def pytest_collection_modifyitems(items):
    for item in items:
        if "tests/integration" in item.nodeid.replace("\\", "/"):
            item.add_marker(pytest.mark.integration)
            if not DATABASE_URL:
                item.add_marker(pytest.mark.skip(reason="DATABASE_URL not set"))


@pytest.fixture(scope="session")
def settings() -> Settings:
    # 10 parallel connections is plenty to race on one row lock, and stays under the
    # 15-client cap of Supabase's free-tier session pooler.
    return Settings(database_url=DATABASE_URL, db_schema=TEST_SCHEMA, pool_max=10)


@pytest.fixture(scope="session")
def client(settings):
    migrate(DATABASE_URL, TEST_SCHEMA, reset=True)
    with TestClient(create_app(settings)) as c:
        yield c


@pytest.fixture
def pool(client):
    """Connections exactly as the app gets them: running as the ledger_app role."""
    return client.app.state.pool


@pytest.fixture
def owner(client):
    """A connection as the schema owner, bypassing the app role: proves the
    database's own guarantees hold even for a fully privileged session."""
    with psycopg.connect(DATABASE_URL, autocommit=True, prepare_threshold=None) as conn:
        conn.execute(sql.SQL("set search_path to {}").format(sql.Identifier(TEST_SCHEMA)))
        yield conn


def dummy_phone() -> str:
    return f"9{random.randrange(10**9):09d}"


def new_account(client, name: str = "Test Holder") -> dict:
    res = client.post("/accounts", json={"name": name, "phone": dummy_phone()})
    assert res.status_code == 201, res.text
    return res.json()


@pytest.fixture
def account(client):
    return new_account(client)


def txn(type_: str, amount, description: str = "test", reference_id: str | None = None) -> dict:
    return {
        "type": type_,
        "amount": amount,
        "description": description,
        "reference_id": reference_id or f"ref-{uuid.uuid4().hex[:12]}",
    }
