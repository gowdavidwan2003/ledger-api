"""The ledger's business rules as pure functions: no I/O, no clock, no database.

The service layer gathers the inputs under a row lock, asks `decide` what to do,
then performs the writes. Keeping the decision pure means every rule is covered by
fast unit tests (tests/unit/test_rules.py) without a database.
"""

from dataclasses import dataclass

from app.domain.errors import InsufficientFunds, ReferenceConflict
from app.domain.models import Transaction, TransactionRequest, TxnType


@dataclass(frozen=True)
class Apply:
    """Write a new transaction and move the balance to new_balance."""

    new_balance: int


@dataclass(frozen=True)
class Replay:
    """The request was already applied; return the original, write nothing."""

    transaction: Transaction


def decide(balance: int, request: TransactionRequest, existing: Transaction | None) -> Apply | Replay:
    """
    balance   current balance of the (locked) account, in minor units
    request   the incoming transaction
    existing  the transaction already stored under request.reference_id, if any
    """
    # Idempotency comes first: a retry of something already applied must return the
    # original result even if the balance has since changed.
    if existing is not None:
        if existing.same_request_as(request):
            return Replay(existing)
        raise ReferenceConflict(existing.id)

    if request.type is TxnType.CREDIT:
        return Apply(balance + request.amount)

    if request.amount > balance:
        raise InsufficientFunds(balance=balance, requested=request.amount)
    return Apply(balance - request.amount)
