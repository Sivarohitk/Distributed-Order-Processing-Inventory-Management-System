import os
import psycopg

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5432/order_db"
)


def get_connection():
    return psycopg.connect(DATABASE_URL)


def init_db():
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