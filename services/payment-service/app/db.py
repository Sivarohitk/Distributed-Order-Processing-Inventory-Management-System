import logging
import os
import time

import psycopg

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5432/order_db"
)
DATABASE_WAIT_TIMEOUT_SECONDS = int(
    os.getenv("DATABASE_WAIT_TIMEOUT_SECONDS", "30")
)
DATABASE_WAIT_INTERVAL_SECONDS = float(
    os.getenv("DATABASE_WAIT_INTERVAL_SECONDS", "1")
)

logger = logging.getLogger(__name__)


def get_connection():
    return psycopg.connect(DATABASE_URL)


def wait_for_database():
    deadline = time.monotonic() + DATABASE_WAIT_TIMEOUT_SECONDS
    last_error = None

    while time.monotonic() < deadline:
        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1")
                    cur.fetchone()
            return
        except psycopg.OperationalError as exc:
            last_error = exc
            logger.info("Waiting for PostgreSQL to become ready")
            time.sleep(DATABASE_WAIT_INTERVAL_SECONDS)

    raise RuntimeError(
        f"Database was not ready within {DATABASE_WAIT_TIMEOUT_SECONDS} seconds"
    ) from last_error


def init_db():
    wait_for_database()

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS payments (
                    payment_id TEXT PRIMARY KEY,
                    order_id TEXT UNIQUE NOT NULL,
                    amount NUMERIC(10, 2) NOT NULL CHECK (amount > 0),
                    currency CHAR(3) NOT NULL,
                    status TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
        conn.commit()
