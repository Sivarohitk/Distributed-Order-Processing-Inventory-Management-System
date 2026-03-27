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
                CREATE TABLE IF NOT EXISTS orders (
                    order_id TEXT PRIMARY KEY,
                    idempotency_key TEXT UNIQUE NOT NULL,
                    customer_id TEXT NOT NULL,
                    sku TEXT NOT NULL,
                    quantity INTEGER NOT NULL CHECK (quantity > 0),
                    amount NUMERIC(10, 2) NOT NULL CHECK (amount > 0),
                    currency CHAR(3) NOT NULL,
                    status TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS workflow_state (
                    order_id TEXT PRIMARY KEY REFERENCES orders(order_id) ON DELETE CASCADE,
                    current_step TEXT NOT NULL,
                    order_status TEXT NOT NULL,
                    inventory_status TEXT NOT NULL,
                    payment_status TEXT NOT NULL,
                    shipment_status TEXT NOT NULL,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS outbox_events (
                    event_id TEXT PRIMARY KEY,
                    aggregate_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    payload JSONB NOT NULL,
                    status TEXT NOT NULL,
                    retry_count INTEGER NOT NULL DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    published_at TIMESTAMP NULL
                )
            """)

            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_outbox_events_status_created_at
                ON outbox_events (status, created_at)
            """)

        conn.commit()
