import logging

from shared.db import (
    get_connection as shared_get_connection,
)
from shared.db import (
    load_database_settings,
    wait_for_database,
)

logger = logging.getLogger(__name__)
DATABASE_SETTINGS = load_database_settings()


def get_connection():
    return shared_get_connection(DATABASE_SETTINGS)


def init_db():
    wait_for_database(DATABASE_SETTINGS, logger)

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS shipments (
                    shipment_id TEXT PRIMARY KEY,
                    order_id TEXT UNIQUE NOT NULL,
                    status TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
        conn.commit()
