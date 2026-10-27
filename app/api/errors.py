"""Maps every failure to one shape: {"error": {"code", "message", "details"}}."""

import logging

import psycopg
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.domain.errors import (
    AccountNotFound,
    DomainError,
    InsufficientFunds,
    InvalidCursor,
    PhoneAlreadyRegistered,
    PhoneNotRegistered,
    ReferenceConflict,
)
from app.domain.money import to_major

log = logging.getLogger("ledger")


def error_response(status: int, code: str, message: str, details=None) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": message, "details": details}}, status_code=status)


def _domain(exc: DomainError) -> JSONResponse:
    match exc:
        case AccountNotFound():
            return error_response(404, "ACCOUNT_NOT_FOUND", str(exc))
        case PhoneNotRegistered():
            return error_response(404, "PHONE_NOT_REGISTERED", str(exc))
        case PhoneAlreadyRegistered():
            return error_response(409, "PHONE_ALREADY_REGISTERED", str(exc))
        case InsufficientFunds():
            details = {"balance": to_major(exc.balance), "requested": to_major(exc.requested)}
            return error_response(422, "INSUFFICIENT_FUNDS", str(exc), details)
        case ReferenceConflict():
            return error_response(
                409, "REFERENCE_ID_CONFLICT", str(exc), {"existing_transaction_id": str(exc.existing_id)}
            )
        case InvalidCursor():
            return error_response(400, "INVALID_CURSOR", str(exc))
    return error_response(400, "BAD_REQUEST", str(exc))


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(DomainError)
    async def domain_error(_: Request, exc: DomainError):
        return _domain(exc)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError):
        details = [
            {"field": ".".join(str(p) for p in err["loc"] if p != "body"), "message": err["msg"]}
            for err in exc.errors()
        ]
        return error_response(400, "VALIDATION_ERROR", "Request validation failed", details)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(_: Request, exc: StarletteHTTPException):
        code = {404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED", 413: "PAYLOAD_TOO_LARGE"}.get(
            exc.status_code, "HTTP_ERROR"
        )
        return error_response(exc.status_code, code, str(exc.detail))

    @app.exception_handler(psycopg.OperationalError)
    async def db_unavailable(_: Request, exc: psycopg.OperationalError):
        # Also covers lock_timeout / statement_timeout: the request was cut short
        # and nothing was committed, so it is safe to retry.
        log.error("database unavailable: %s", type(exc).__name__)
        return error_response(503, "DATABASE_UNAVAILABLE", "The database is temporarily unavailable, retry shortly")

    @app.exception_handler(psycopg.DataError)
    async def db_rejected_value(_: Request, exc: psycopg.DataError):
        # Validation should catch bad input first; this keeps anything that slips
        # past it a client error rather than a 500.
        log.warning("database rejected a value: %s", type(exc).__name__)
        return error_response(400, "VALIDATION_ERROR", "A value in the request was rejected by the database")

    @app.exception_handler(Exception)
    async def unhandled(_: Request, exc: Exception):
        log.exception("unhandled error", exc_info=exc)
        return error_response(500, "INTERNAL_ERROR", "Something went wrong")
