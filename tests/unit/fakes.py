"""In-memory stand-in for LedgerService, so the HTTP layer can be tested without a
database. It uses the real domain rules; only storage is faked."""

import uuid
from datetime import UTC, datetime, timedelta

from app.domain import rules
from app.domain.errors import AccountNotFound, PhoneAlreadyRegistered, PhoneNotRegistered
from app.domain.models import Account, Transaction, TransactionRequest, TxnType
from app.services import pagination


class FakeLedgerService:
    def __init__(self):
        self.accounts: dict[uuid.UUID, Account] = {}
        self.txns: list[Transaction] = []
        self._clock = datetime(2026, 1, 1, tzinfo=UTC)

    def _now(self) -> datetime:
        self._clock += timedelta(seconds=1)
        return self._clock

    def create_account(self, name: str, phone: str) -> Account:
        if any(a.phone == phone for a in self.accounts.values()):
            raise PhoneAlreadyRegistered()
        acct = Account(id=uuid.uuid4(), name=name, phone=phone, balance=0, created_at=self._now())
        self.accounts[acct.id] = acct
        return acct

    def find_by_phone(self, phone: str) -> Account:
        match = next((a for a in self.accounts.values() if a.phone == phone), None)
        if match is None:
            raise PhoneNotRegistered()
        return match

    def get_account(self, account_id: uuid.UUID) -> Account:
        if account_id not in self.accounts:
            raise AccountNotFound(account_id)
        return self.accounts[account_id]

    def post_transaction(self, account_id: uuid.UUID, request: TransactionRequest) -> tuple[Transaction, bool]:
        acct = self.get_account(account_id)
        existing = next(
            (t for t in self.txns if t.account_id == account_id and t.reference_id == request.reference_id), None
        )
        decision = rules.decide(acct.balance, request, existing)
        if isinstance(decision, rules.Replay):
            return decision.transaction, False
        txn = Transaction(
            id=uuid.uuid4(),
            account_id=account_id,
            type=request.type,
            amount=request.amount,
            description=request.description,
            reference_id=request.reference_id,
            balance_after=decision.new_balance,
            created_at=self._now(),
        )
        self.accounts[account_id] = Account(acct.id, acct.name, acct.phone, decision.new_balance, acct.created_at)
        self.txns.append(txn)
        return txn, True

    def list_transactions(self, account_id, limit, cursor, txn_type: TxnType | None):
        self.get_account(account_id)
        after = pagination.decode(cursor) if cursor else None
        rows = sorted(
            (t for t in self.txns if t.account_id == account_id and (txn_type is None or t.type == txn_type)),
            key=lambda t: (t.created_at, t.id),
            reverse=True,
        )
        if after:
            rows = [t for t in rows if (t.created_at, t.id) < after]
        page = rows[:limit]
        next_cursor = pagination.encode(page[-1].created_at, page[-1].id) if len(rows) > limit else None
        return page, next_cursor
