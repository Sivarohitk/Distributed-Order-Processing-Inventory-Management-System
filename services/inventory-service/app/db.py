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
                CREATE TABLE IF NOT EXISTS inventory_stock (
                    sku TEXT PRIMARY KEY,
                    available_quantity INTEGER NOT NULL CHECK (available_quantity >= 0),
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS inventory_reservations (
                    reservation_id TEXT PRIMARY KEY,
                    order_id TEXT UNIQUE NOT NULL,
                    sku TEXT NOT NULL,
                    quantity INTEGER NOT NULL CHECK (quantity > 0),
                    status TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            cur.execute("""
                INSERT INTO inventory_stock (sku, available_quantity)
                VALUES
                    ('SKU-CHAIR-01', 10),
                    ('SKU-TABLE-01', 5),
                    ('SKU-LAMP-01', 20)
                ON CONFLICT (sku) DO NOTHING
            """)

        conn.commit()
