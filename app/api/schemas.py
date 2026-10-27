"""HTTP request/response shapes. Conversion to and from domain objects lives here,
so routes never deal with minor units."""

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StringConstraints

from app.domain import phone, text
from app.domain.models import Account, Transaction, TransactionRequest, TxnType
from app.domain.money import MAX_AMOUNT, to_major, to_minor

Name = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100), AfterValidator(text.clean)
]
Phone = Annotated[
    str,
    StringConstraints(max_length=20),
    AfterValidator(phone.normalize),
    Field(
        description="10-digit Indian mobile; +91 / 0 prefixes, spaces and dashes are accepted", examples=["9000000001"]
    ),
]
Description = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255), AfterValidator(text.clean)
]
ReferenceId = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100), AfterValidator(text.clean)
]
Amount = Annotated[Decimal, Field(gt=0, le=MAX_AMOUNT, decimal_places=2, examples=["150.00"])]
MoneyStr = Annotated[str, Field(pattern=r"^-?\d+\.\d{2}$", examples=["150.00"])]


class AccountCreate(BaseModel):
    # extra="forbid": sending balance/id/created_at is a 400, never silently ignored.
    model_config = ConfigDict(extra="forbid")

    name: Name
    phone: Phone


class PhoneLookup(BaseModel):
    model_config = ConfigDict(extra="forbid")

    phone: Phone


class AccountOut(BaseModel):
    id: UUID
    name: str
    phone: str = Field(description="Masked; the full number is never returned", examples=["+91 ******0001"])
    balance: MoneyStr
    created_at: datetime

    @classmethod
    def of(cls, a: Account) -> "AccountOut":
        return cls(
            id=a.id, name=a.name, phone=phone.mask(a.phone), balance=to_major(a.balance), created_at=a.created_at
        )


class BalanceOut(BaseModel):
    account_id: UUID
    balance: MoneyStr


class TransactionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["credit", "debit"]
    amount: Amount
    description: Description
    reference_id: ReferenceId = Field(description="Client idempotency key, unique per account")

    def to_domain(self) -> TransactionRequest:
        return TransactionRequest(
            type=TxnType(self.type),
            amount=to_minor(self.amount),
            description=self.description,
            reference_id=self.reference_id,
        )


class TransactionOut(BaseModel):
    id: UUID
    account_id: UUID
    type: Literal["credit", "debit"]
    amount: MoneyStr
    description: str
    reference_id: str
    balance_after: MoneyStr
    created_at: datetime

    @classmethod
    def of(cls, t: Transaction) -> "TransactionOut":
        return cls(
            id=t.id,
            account_id=t.account_id,
            type=t.type.value,
            amount=to_major(t.amount),
            description=t.description,
            reference_id=t.reference_id,
            balance_after=to_major(t.balance_after),
            created_at=t.created_at,
        )


class TransactionPage(BaseModel):
    data: list[TransactionOut]
    next_cursor: str | None


class ErrorBody(BaseModel):
    code: str
    message: str
    details: dict | list | None = None


class ErrorResponse(BaseModel):
    error: ErrorBody
