"""The business rules, exhaustively, with no database."""

import uuid
from datetime import UTC, datetime

import pytest

from app.domain.errors import InsufficientFunds, ReferenceConflict
from app.domain.models import Transaction, TransactionRequest, TxnType
from app.domain.rules import Apply, Replay, decide


def req(type_=TxnType.CREDIT, amount=1000, description="d", reference_id="r1") -> TransactionRequest:
    return TransactionRequest(type=type_, amount=amount, description=description, reference_id=reference_id)


def stored(request: TransactionRequest, balance_after: int = 0) -> Transaction:
    return Transaction(
        id=uuid.uuid4(),
        account_id=uuid.uuid4(),
        type=request.type,
        amount=request.amount,
        description=request.description,
        reference_id=request.reference_id,
        balance_after=balance_after,
        created_at=datetime.now(UTC),
    )


def test_credit_adds_amount():
    assert decide(10000, req(TxnType.CREDIT, 5000), None) == Apply(15000)


def test_credit_on_zero_balance():
    assert decide(0, req(TxnType.CREDIT, 1), None) == Apply(1)


def test_debit_subtracts_amount():
    assert decide(10000, req(TxnType.DEBIT, 2500), None) == Apply(7500)


def test_debit_of_entire_balance_reaches_zero():
    assert decide(10000, req(TxnType.DEBIT, 10000), None) == Apply(0)


@pytest.mark.parametrize(("balance", "amount"), [(0, 1), (5000, 10000), (9999, 10000)])
def test_debit_above_balance_is_rejected(balance, amount):
    with pytest.raises(InsufficientFunds) as exc:
        decide(balance, req(TxnType.DEBIT, amount), None)
    assert (exc.value.balance, exc.value.requested) == (balance, amount)


def test_identical_retry_replays_original():
    original = stored(req(), balance_after=1000)
    assert decide(1000, req(), original) == Replay(original)


def test_retry_replays_even_if_balance_changed_since():
    # The debit was applied when balance was 100; balance is now 0. A retry must
    # return the original success, not re-run the check and report insufficient funds.
    original = stored(req(TxnType.DEBIT, 10000), balance_after=0)
    assert decide(0, req(TxnType.DEBIT, 10000), original) == Replay(original)


@pytest.mark.parametrize(
    "changed",
    [
        {"amount": 999},
        {"type_": TxnType.DEBIT},
        {"description": "something else"},
    ],
)
def test_reused_reference_with_different_payload_conflicts(changed):
    original = stored(req())
    with pytest.raises(ReferenceConflict) as exc:
        decide(1000, req(**changed), original)
    assert exc.value.existing_id == original.id
