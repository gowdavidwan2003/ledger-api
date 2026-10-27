"""Use cases. Each function owns its database transaction; rules live in app.domain.rules."""

from uuid import UUID

from psycopg import errors as pg_errors
from psycopg_pool import ConnectionPool

from app.domain import rules
from app.domain.errors import (
    AccountNotFound,
    InsufficientFunds,
    PhoneAlreadyRegistered,
    PhoneNotRegistered,
    ReferenceConflict,
)
from app.domain.models import Account, Transaction, TransactionRequest, TxnType
from app.repositories import accounts, transactions
from app.services import pagination


class LedgerService:
    def __init__(self, pool: ConnectionPool):
        self._pool = pool

    def create_account(self, name: str, phone: str) -> Account:
        try:
            with self._pool.connection() as conn:
                return accounts.insert(conn, name, phone)
        except pg_errors.UniqueViolation:
            # The unique constraint is the check: no read-then-insert race.
            raise PhoneAlreadyRegistered() from None

    def find_by_phone(self, phone: str) -> Account:
        with self._pool.connection() as conn:
            account = accounts.get_by_phone(conn, phone)
        if account is None:
            raise PhoneNotRegistered()
        return account

    def get_account(self, account_id: UUID) -> Account:
        with self._pool.connection() as conn:
            account = accounts.get(conn, account_id)
        if account is None:
            raise AccountNotFound(account_id)
        return account

    def post_transaction(self, account_id: UUID, request: TransactionRequest) -> tuple[Transaction, bool]:
        """Returns (transaction, created). created=False is an idempotent replay.

        Everything below runs in one database transaction holding a row lock on the
        account. Concurrent requests for the same account queue on that lock, so
        two debits can never both pass the balance check, and two requests with the
        same reference_id can never both insert. Other accounts are unaffected.
        """
        try:
            with self._pool.connection() as conn, conn.transaction():
                balance = accounts.lock_balance(conn, account_id)
                if balance is None:
                    raise AccountNotFound(account_id)

                existing = transactions.find_by_reference(conn, account_id, request.reference_id)
                decision = rules.decide(balance, request, existing)
                if isinstance(decision, rules.Replay):
                    return decision.transaction, False

                accounts.set_balance(conn, account_id, decision.new_balance)
                return transactions.insert(conn, account_id, request, decision.new_balance), True

        # The lock makes these unreachable in practice. They are the database's
        # backstops, translated so even a logic bug surfaces as the right error.
        except pg_errors.UniqueViolation:
            with self._pool.connection() as conn:
                existing = transactions.find_by_reference(conn, account_id, request.reference_id)
            if existing is None:
                raise
            raise ReferenceConflict(existing.id) from None
        except pg_errors.CheckViolation:
            raise InsufficientFunds(self.get_account(account_id).balance, request.amount) from None

    def list_transactions(
        self, account_id: UUID, limit: int, cursor: str | None, txn_type: TxnType | None
    ) -> tuple[list[Transaction], str | None]:
        after = pagination.decode(cursor) if cursor else None
        with self._pool.connection() as conn:
            if not accounts.exists(conn, account_id):
                raise AccountNotFound(account_id)
            # Fetch one extra row to know whether another page exists.
            rows = transactions.list_page(conn, account_id, limit + 1, after, txn_type)

        page = rows[:limit]
        next_cursor = pagination.encode(page[-1].created_at, page[-1].id) if len(rows) > limit else None
        return page, next_cursor
