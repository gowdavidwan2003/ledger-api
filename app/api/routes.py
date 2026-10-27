from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response, status

from app.api.schemas import (
    AccountCreate,
    AccountOut,
    BalanceOut,
    ErrorResponse,
    PhoneLookup,
    TransactionCreate,
    TransactionOut,
    TransactionPage,
)
from app.domain.models import TxnType
from app.domain.money import to_major
from app.services.ledger import LedgerService

router = APIRouter()


def get_service(request: Request) -> LedgerService:
    return request.app.state.ledger


Service = Annotated[LedgerService, Depends(get_service)]

_errors = {
    400: {"model": ErrorResponse, "description": "Validation error"},
    404: {"model": ErrorResponse, "description": "Account not found"},
}


@router.post(
    "/accounts",
    response_model=AccountOut,
    status_code=status.HTTP_201_CREATED,
    tags=["accounts"],
    responses={
        400: _errors[400],
        409: {"model": ErrorResponse, "description": "Phone number already registered"},
    },
)
def create_account(body: AccountCreate, service: Service):
    """Create an account. Balance always starts at 0.00; id and created_at are generated."""
    return AccountOut.of(service.create_account(body.name, body.phone))


@router.post(
    "/accounts/lookup",
    response_model=AccountOut,
    tags=["accounts"],
    responses={400: _errors[400], 404: {"model": ErrorResponse, "description": "Phone number not registered"}},
)
def find_account_by_phone(body: PhoneLookup, service: Service):
    """Find an account by phone number. POST rather than GET so the number travels in
    the body and never ends up in URLs, proxy logs or browser history.
    Not authentication: a real system would verify the number with an OTP first."""
    return AccountOut.of(service.find_by_phone(body.phone))


@router.get("/accounts/{account_id}", response_model=AccountOut, tags=["accounts"], responses=_errors)
def get_account(account_id: UUID, service: Service):
    return AccountOut.of(service.get_account(account_id))


@router.get("/accounts/{account_id}/balance", response_model=BalanceOut, tags=["accounts"], responses=_errors)
def get_balance(account_id: UUID, service: Service):
    account = service.get_account(account_id)
    return BalanceOut(account_id=account.id, balance=to_major(account.balance))


@router.post(
    "/accounts/{account_id}/transactions",
    response_model=TransactionOut,
    status_code=status.HTTP_201_CREATED,
    tags=["transactions"],
    responses={
        **_errors,
        200: {"model": TransactionOut, "description": "Idempotent replay: this reference_id was already applied"},
        409: {"model": ErrorResponse, "description": "reference_id reused with a different payload"},
        422: {"model": ErrorResponse, "description": "Insufficient funds for a debit"},
    },
)
def add_transaction(account_id: UUID, body: TransactionCreate, response: Response, service: Service):
    """Credit or debit an account. Retrying with the same reference_id is safe:
    the original transaction is returned with 200 and nothing is applied twice."""
    txn, created = service.post_transaction(account_id, body.to_domain())
    if not created:
        response.status_code = status.HTTP_200_OK
        response.headers["Idempotent-Replayed"] = "true"
    return TransactionOut.of(txn)


@router.get(
    "/accounts/{account_id}/transactions", response_model=TransactionPage, tags=["transactions"], responses=_errors
)
def list_transactions(
    account_id: UUID,
    service: Service,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    cursor: Annotated[str | None, Query(description="next_cursor from the previous page")] = None,
    type: Annotated[Literal["credit", "debit"] | None, Query()] = None,
):
    """Transaction history, newest first."""
    page, next_cursor = service.list_transactions(account_id, limit, cursor, TxnType(type) if type else None)
    return TransactionPage(data=[TransactionOut.of(t) for t in page], next_cursor=next_cursor)
