"""Business-rule failures. They know nothing about HTTP; app/api/errors.py maps them."""

from uuid import UUID


class DomainError(Exception):
    pass


class AccountNotFound(DomainError):
    def __init__(self, account_id: UUID):
        super().__init__(f"Account {account_id} does not exist")
        self.account_id = account_id


class PhoneNotRegistered(DomainError):
    def __init__(self):
        super().__init__("No account is registered with this phone number")


class PhoneAlreadyRegistered(DomainError):
    def __init__(self):
        super().__init__("An account with this phone number already exists")


class InsufficientFunds(DomainError):
    def __init__(self, balance: int, requested: int):
        super().__init__("Debit rejected: balance is lower than the amount")
        self.balance = balance
        self.requested = requested


class ReferenceConflict(DomainError):
    def __init__(self, existing_id: UUID):
        super().__init__("reference_id was already used on this account for a different transaction")
        self.existing_id = existing_id


class InvalidCursor(DomainError):
    def __init__(self):
        super().__init__("cursor is malformed")
