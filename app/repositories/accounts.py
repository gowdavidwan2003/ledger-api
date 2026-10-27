from uuid import UUID

from psycopg import Connection

from app.domain.models import Account

_COLUMNS = "id, name, phone, balance, created_at"


def _account(row: dict) -> Account:
    return Account(**row)


def insert(conn: Connection, name: str, phone: str) -> Account:
    # balance and created_at come from column defaults; the client never sets them.
    row = conn.execute(
        f"insert into accounts (name, phone) values (%s, %s) returning {_COLUMNS}", (name, phone)
    ).fetchone()
    return _account(row)


def get(conn: Connection, account_id: UUID) -> Account | None:
    row = conn.execute(f"select {_COLUMNS} from accounts where id = %s", (account_id,)).fetchone()
    return _account(row) if row else None


def get_by_phone(conn: Connection, phone: str) -> Account | None:
    row = conn.execute(f"select {_COLUMNS} from accounts where phone = %s", (phone,)).fetchone()
    return _account(row) if row else None


def exists(conn: Connection, account_id: UUID) -> bool:
    return conn.execute("select 1 from accounts where id = %s", (account_id,)).fetchone() is not None


def lock_balance(conn: Connection, account_id: UUID) -> int | None:
    """Locks the account row until the surrounding transaction ends. Any other
    request for the same account waits here, so balance checks can't interleave."""
    row = conn.execute("select balance from accounts where id = %s for update", (account_id,)).fetchone()
    return row["balance"] if row else None


def set_balance(conn: Connection, account_id: UUID, balance: int) -> None:
    conn.execute("update accounts set balance = %s where id = %s", (balance, account_id))
