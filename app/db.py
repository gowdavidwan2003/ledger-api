from psycopg import Connection, sql
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from app.config import Settings


def create_pool(settings: Settings) -> ConnectionPool:
    def configure(conn: Connection) -> None:
        # Drop to the least-privileged role first: from here on this connection
        # can read/insert ledger rows and update balances, and nothing else.
        if settings.db_app_role:
            conn.execute(sql.SQL("set role {}").format(sql.Identifier(settings.db_app_role)))
        # Supabase's pooler drops startup options, so session settings go here.
        conn.execute(sql.SQL("set search_path to {}").format(sql.Identifier(settings.db_schema)))
        # Without these, one stuck transaction holding an account's row lock would
        # make every other request for that account wait until the pool gave up.
        conn.execute(sql.SQL("set lock_timeout = {}").format(sql.Literal(settings.lock_timeout_ms)))
        conn.execute(sql.SQL("set statement_timeout = {}").format(sql.Literal(settings.statement_timeout_ms)))
        conn.execute("set idle_in_transaction_session_timeout = 10000")

    pool = ConnectionPool(
        settings.database_url,
        min_size=settings.pool_min,
        max_size=settings.pool_max,
        kwargs={
            "row_factory": dict_row,
            # Autocommit for single reads; writes open an explicit conn.transaction().
            "autocommit": True,
            # Server-side prepared statements break behind PgBouncer-style poolers.
            "prepare_threshold": None,
        },
        configure=configure,
        open=True,
    )
    pool.wait(timeout=30)
    return pool
