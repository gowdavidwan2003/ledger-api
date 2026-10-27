"""Request IDs and one structured log line per request."""

import json
import logging
import re
import time
import uuid

from fastapi import FastAPI, Request

log = logging.getLogger("ledger.http")

REQUEST_ID = re.compile(r"[A-Za-z0-9._-]{1,64}")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry = {"level": record.levelname, "logger": record.name, "msg": record.getMessage()}
        entry.update(getattr(record, "fields", {}))
        if record.exc_info:
            entry["exc"] = self.formatException(record.exc_info)
        return json.dumps(entry)


def configure_logging(level: str) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger("ledger")
    root.handlers[:] = [handler]
    root.setLevel(level)
    root.propagate = False


def add_request_context(app: FastAPI) -> None:
    @app.middleware("http")
    async def request_context(request: Request, call_next):
        # Honour a caller's ID so a request can be traced across services, but only
        # if it looks like an ID: it is echoed in a header and written to logs.
        incoming = request.headers.get("X-Request-ID", "")
        request_id = incoming if REQUEST_ID.fullmatch(incoming) else uuid.uuid4().hex
        start = time.perf_counter()
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        # Account data must not be cached by browsers or shared proxies.
        response.headers.setdefault("Cache-Control", "no-store")
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        log.info(
            "request",
            extra={
                "fields": {
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "status": response.status_code,
                    "ms": round((time.perf_counter() - start) * 1000, 1),
                }
            },
        )
        return response
