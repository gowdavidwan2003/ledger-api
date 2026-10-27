from datetime import datetime
from uuid import UUID

from psycopg import Connection

from app.domain.models import Transaction, TransactionRequest, TxnType

_COLUMNS = "id, account_id, type, amount, description, reference_id, balance_after, created_at"


def _transaction(row: dict) -> Transaction:
    return Transaction(**{**row, "type": TxnType(row["type"])})


def find_by_reference(conn: Connection, account_id: UUID, reference_id: str) -> Transaction | None:
    row = conn.execute(
        f"select {_COLUMNS} from transactions where account_id = %s and reference_id = %s",
        (account_id, reference_id),
    ).fetchone()
    return _transaction(row) if row else None


def insert(conn: Connection, account_id: UUID, request: TransactionRequest, balance_after: int) -> Transaction:
    row = conn.execute(
        f"""
        insert into transactions (account_id, type, amount, description, reference_id, balance_after)
        values (%s, %s::txn_type, %s, %s, %s, %s)
        returning {_COLUMNS}
        """,
        (account_id, request.type.value, request.amount, request.description, request.reference_id, balance_after),
    ).fetchone()
    return _transaction(row)


def list_page(
    conn: Connection,
    account_id: UUID,
    limit: int,
    after: tuple[datetime, UUID] | None,
    txn_type: TxnType | None,
) -> list[Transaction]:
    """Newest first. Keyset pagination on (created_at, id): page N costs the same
    as page 1, and rows inserted while a client pages through don't shift pages."""
    rows = conn.execute(
        f"""
        select {_COLUMNS}
          from transactions
         where account_id = %(account_id)s
           and (%(type)s::txn_type is null or type = %(type)s::txn_type)
           and (%(after_ts)s::timestamptz is null
                or (created_at, id) < (%(after_ts)s::timestamptz, %(after_id)s::uuid))
         order by created_at desc, id desc
         limit %(limit)s
        """,
        {
            "account_id": account_id,
            "type": txn_type.value if txn_type else None,
            "after_ts": after[0] if after else None,
            "after_id": after[1] if after else None,
            "limit": limit,
        },
    ).fetchall()
    return [_transaction(r) for r in rows]
