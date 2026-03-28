import logging
import os
import time
from dataclasses import dataclass

import psycopg

DEFAULT_DATABASE_URL = "postgresql://postgres:postgres@localhost:5432/order_db"
DEFAULT_DATABASE_WAIT_TIMEOUT_SECONDS = 30
DEFAULT_DATABASE_WAIT_INTERVAL_SECONDS = 1.0


@dataclass(frozen=True)
class DatabaseSettings:
    url: str
    wait_timeout_seconds: int
    wait_interval_seconds: float


def load_database_settings(
    *,
    default_url: str = DEFAULT_DATABASE_URL,
    default_wait_timeout_seconds: int = DEFAULT_DATABASE_WAIT_TIMEOUT_SECONDS,
    default_wait_interval_seconds: float = DEFAULT_DATABASE_WAIT_INTERVAL_SECONDS,
) -> DatabaseSettings:
    return DatabaseSettings(
        url=os.getenv("DATABASE_URL", default_url),
        wait_timeout_seconds=int(
            os.getenv(
                "DATABASE_WAIT_TIMEOUT_SECONDS",
                str(default_wait_timeout_seconds),
            )
        ),
        wait_interval_seconds=float(
            os.getenv(
                "DATABASE_WAIT_INTERVAL_SECONDS",
                str(default_wait_interval_seconds),
            )
        ),
    )


def get_connection(settings: DatabaseSettings):
    return psycopg.connect(settings.url)


def wait_for_database(settings: DatabaseSettings, logger: logging.Logger):
    deadline = time.monotonic() + settings.wait_timeout_seconds
    last_error = None

    while time.monotonic() < deadline:
        try:
            with get_connection(settings) as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1")
                    cur.fetchone()
            return
        except psycopg.OperationalError as exc:
            last_error = exc
            logger.info("Waiting for PostgreSQL to become ready")
            time.sleep(settings.wait_interval_seconds)

    raise RuntimeError(
        f"Database was not ready within {settings.wait_timeout_seconds} seconds"
    ) from last_error
