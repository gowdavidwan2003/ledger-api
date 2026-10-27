from contextlib import asynccontextmanager

from fastapi import FastAPI, Request

from app.api.errors import register_error_handlers
from app.api.limits import BodySizeLimit
from app.api.routes import router
from app.config import MAX_BODY_BYTES, Settings
from app.db import create_pool
from app.observability import add_request_context, configure_logging
from app.services.ledger import LedgerService


def create_app(settings: Settings | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        s = settings or Settings.from_env()
        configure_logging(s.log_level)
        pool = create_pool(s)
        app.state.pool = pool
        app.state.ledger = LedgerService(pool)
        try:
            yield
        finally:
            pool.close()

    app = FastAPI(
        title="Transaction Ledger API",
        version="1.1.0",
        description=(
            "Accounts with credit/debit transactions.\n\n"
            'Amounts are decimal strings with 2 places (e.g. `"150.00"`), stored internally as '
            'integer minor units. Every error uses the shape `{"error": {code, message, details}}`; '
            "each code is explained in docs/ERRORS.md."
        ),
        lifespan=lifespan,
    )
    register_error_handlers(app)
    add_request_context(app)
    app.add_middleware(BodySizeLimit, max_bytes=MAX_BODY_BYTES)
    app.include_router(router)

    @app.get("/health", tags=["meta"])
    def health(request: Request):
        with request.app.state.pool.connection() as conn:
            conn.execute("select 1")
        return {"status": "ok"}

    return app


app = create_app()
