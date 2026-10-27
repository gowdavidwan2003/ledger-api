"""Apply db/migrations/*.sql to a schema, once each, in filename order.

    python scripts/migrate.py                         # schema from DB_SCHEMA (default: ledger)
    python scripts/migrate.py --schema ledger_test --reset

Applied versions are recorded in <schema>.schema_migrations, so re-running is a
no-op. Each file runs in its own transaction: a failing migration leaves nothing
half-applied. --reset drops the schema first (the test suite uses it).
"""

import argparse
import os
import sys
from pathlib import Path

import psycopg
from dotenv import load_dotenv
from psycopg import sql

ROOT = Path(__file__).resolve().parent.parent
MIGRATIONS = ROOT / "db" / "migrations"


def migrate(database_url: str, schema: str, reset: bool = False) -> list[str]:
    applied_now = []
    schema_id = sql.Identifier(schema)
    with psycopg.connect(database_url, prepare_threshold=None, autocommit=True) as conn:
        if reset:
            conn.execute(sql.SQL("drop schema if exists {} cascade").format(schema_id))
        conn.execute(sql.SQL("create schema if not exists {}").format(schema_id))
        conn.execute(sql.SQL("set search_path to {}").format(schema_id))
        conn.execute(
            "create table if not exists schema_migrations ("
            " version text primary key, applied_at timestamptz not null default now())"
        )
        done = {r[0] for r in conn.execute("select version from schema_migrations")}

        for path in sorted(MIGRATIONS.glob("*.sql")):
            if path.name in done:
                continue
            with conn.transaction():
                conn.execute(path.read_text(encoding="utf-8"))
                conn.execute("insert into schema_migrations (version) values (%s)", (path.name,))
            applied_now.append(path.name)
    return applied_now


def main() -> None:
    load_dotenv(ROOT / ".env")
    parser = argparse.ArgumentParser()
    parser.add_argument("--schema", default=os.getenv("DB_SCHEMA", "ledger"))
    parser.add_argument("--reset", action="store_true", help="drop the schema first (destroys its data)")
    args = parser.parse_args()

    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        sys.exit("DATABASE_URL is not set (copy .env.example to .env)")
    applied = migrate(database_url, args.schema, args.reset)
    print(f"{args.schema}: applied {', '.join(applied)}" if applied else f"{args.schema}: up to date")


if __name__ == "__main__":
    main()
