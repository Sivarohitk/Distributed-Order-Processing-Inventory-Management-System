import logging
from uuid import uuid4

from fastapi import FastAPI, Header, HTTPException
from psycopg.rows import dict_row

from .db import get_connection, init_db
from .schemas import OrderCreate, OrderResponse

app = FastAPI(title="Order Service", version="0.2.0")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@app.on_event("startup")
def startup_event():
    init_db()
    logger.info("Database initialized")


@app.get("/health")
def health():
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
        return {
            "status": "ok",
            "service": "order-service",
            "database": "connected"
        }
    except Exception:
        logger.exception("Health check failed")
        raise HTTPException(status_code=503, detail="Database unavailable")


@app.post("/orders", response_model=OrderResponse)
def create_order(
    payload: OrderCreate,
    idempotency_key: str = Header(default=None, alias="Idempotency-Key")
):
    if not idempotency_key:
        raise HTTPException(
            status_code=400,
            detail="Idempotency-Key header is required"
        )

    new_order_id = str(uuid4())

    with get_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("""
                INSERT INTO orders (
                    order_id,
                    idempotency_key,
                    customer_id,
                    sku,
                    quantity,
                    amount,
                    currency,
                    status
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (idempotency_key)
                DO UPDATE SET idempotency_key = EXCLUDED.idempotency_key
                RETURNING order_id, customer_id, sku, quantity, amount, currency, status
            """, (
                new_order_id,
                idempotency_key,
                payload.customer_id,
                payload.sku,
                payload.quantity,
                payload.amount,
                payload.currency.upper(),
                "PENDING"
            ))

            order = cur.fetchone()
        conn.commit()

    logger.info("Stored order %s", order["order_id"])

    return {
        **order,
        "message": "Order stored successfully"
    }


@app.get("/orders/{order_id}", response_model=OrderResponse)
def get_order(order_id: str):
    with get_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("""
                SELECT order_id, customer_id, sku, quantity, amount, currency, status
                FROM orders
                WHERE order_id = %s
            """, (order_id,))
            order = cur.fetchone()

    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    return {
        **order,
        "message": "Order fetched successfully"
    }