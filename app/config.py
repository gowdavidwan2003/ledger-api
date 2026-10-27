import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

# Read at app construction, not from Settings, so the HTTP layer can be built (and
# unit-tested) without database configuration.
MAX_BODY_BYTES = int(os.getenv("MAX_BODY_BYTES", "16384"))


@dataclass(frozen=True)
class Settings:
    database_url: str
    db_schema: str = "ledger"
    # Role the app switches to on every connection; see db/migrations/003.
    # Empty string disables the switch (e.g. a database without that role).
    db_app_role: str = "ledger_app"
    pool_min: int = 1
    pool_max: int = 10
    # A request may wait this long for another request's row lock...
    lock_timeout_ms: int = 3000
    # ...and run any single statement this long, before it is cancelled (503).
    statement_timeout_ms: int = 5000
    log_level: str = "INFO"

    @classmethod
    def from_env(cls) -> "Settings":
        database_url = os.getenv("DATABASE_URL")
        if not database_url:
            raise RuntimeError("DATABASE_URL is not set (copy .env.example to .env)")
        return cls(
            database_url=database_url,
            db_schema=os.getenv("DB_SCHEMA", cls.db_schema),
            db_app_role=os.getenv("DB_APP_ROLE", cls.db_app_role),
            pool_min=int(os.getenv("DB_POOL_MIN", cls.pool_min)),
            pool_max=int(os.getenv("DB_POOL_MAX", cls.pool_max)),
            lock_timeout_ms=int(os.getenv("DB_LOCK_TIMEOUT_MS", cls.lock_timeout_ms)),
            statement_timeout_ms=int(os.getenv("DB_STATEMENT_TIMEOUT_MS", cls.statement_timeout_ms)),
            log_level=os.getenv("LOG_LEVEL", cls.log_level),
        )
