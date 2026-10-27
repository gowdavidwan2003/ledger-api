from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID


class TxnType(StrEnum):
    CREDIT = "credit"
    DEBIT = "debit"


@dataclass(frozen=True)
class Account:
    id: UUID
    name: str
    phone: str  # E.164, e.g. +919876543210
    balance: int  # minor units (paise)
    created_at: datetime


@dataclass(frozen=True)
class TransactionRequest:
    type: TxnType
    amount: int  # minor units, > 0
    description: str
    reference_id: str


@dataclass(frozen=True)
class Transaction:
    id: UUID
    account_id: UUID
    type: TxnType
    amount: int
    description: str
    reference_id: str
    balance_after: int
    created_at: datetime

    def same_request_as(self, request: TransactionRequest) -> bool:
        return self.type == request.type and self.amount == request.amount and self.description == request.description
