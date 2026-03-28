import json
import logging
from uuid import uuid4

from fastapi import FastAPI, Header, HTTPException
from psycopg.rows import dict_row

from .db import get_connection, init_db
from .schemas import (
    OrderCreate,
    OrderResponse,
    OutboxEventResponse,
    WorkflowStateResponse,
)

app = FastAPI(title="Order Service", version="0.3.0")

SERVICE_NAME = "order-service"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(SERVICE_NAME)


def log_structured(action: str, level: int = logging.INFO, **fields):
    payload = {"service": SERVICE_NAME, "action": action}
    payload.update({key: value for key, value in fields.items() if value is not None})
    logger.log(level, json.dumps(payload, sort_keys=True, default=str))


def log_exception(action: str, **fields):
    payload = {"service": SERVICE_NAME, "action": action}
    payload.update({key: value for key, value in fields.items() if value is not None})
    logger.exception(json.dumps(payload, sort_keys=True, default=str))


@app.on_event("startup")
def startup_event():
    init_db()
    log_structured("startup_complete", status="ready")


@app.get("/health")
def health():
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()

        return {"status": "ok", "service": SERVICE_NAME, "database": "connected"}
    except Exception:
        log_exception("health_check_failed", status="unavailable")
        raise HTTPException(status_code=503, detail="Database unavailable")


@app.post("/orders", response_model=OrderResponse)
def create_order(
    payload: OrderCreate, idempotency_key: str = Header(default=None, alias="Idempotency-Key")
):
    if not idempotency_key:
        raise HTTPException(status_code=400, detail="Idempotency-Key header is required")

    with get_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT order_id, customer_id, sku, quantity, amount, currency, status
                FROM orders
                WHERE idempotency_key = %s
            """,
                (idempotency_key,),
            )
            existing_order = cur.fetchone()

            if existing_order:
                log_structured(
                    "order_deduplicated",
                    event_type="order.created",
                    order_id=existing_order["order_id"],
                    status=existing_order["status"],
                    result="duplicate_request",
                    idempotency_key=idempotency_key,
                )
                return {
                    **existing_order,
                    "message": "Order already exists for this idempotency key",
                }

            order_id = str(uuid4())
            event_id = str(uuid4())

            order = {
                "order_id": order_id,
                "customer_id": payload.customer_id,
                "sku": payload.sku,
                "quantity": payload.quantity,
                "amount": payload.amount,
                "currency": payload.currency.upper(),
                "status": "PENDING",
            }

            cur.execute(
                """
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
            """,
                (
                    order["order_id"],
                    idempotency_key,
                    order["customer_id"],
                    order["sku"],
                    order["quantity"],
                    order["amount"],
                    order["currency"],
                    order["status"],
                ),
            )

            cur.execute(
                """
                INSERT INTO workflow_state (
                    order_id,
                    current_step,
                    order_status,
                    inventory_status,
                    payment_status,
                    shipment_status
                )
                VALUES (%s, %s, %s, %s, %s, %s)
            """,
                (
                    order_id,
                    "ORDER_CREATED",
                    "PENDING",
                    "NOT_STARTED",
                    "NOT_STARTED",
                    "NOT_STARTED",
                ),
            )

            event_payload = {
                "order_id": order_id,
                "customer_id": payload.customer_id,
                "sku": payload.sku,
                "quantity": payload.quantity,
                "amount": payload.amount,
                "currency": payload.currency.upper(),
                "idempotency_key": idempotency_key,
            }

            cur.execute(
                """
                INSERT INTO outbox_events (
                    event_id,
                    aggregate_id,
                    event_type,
                    payload,
                    status
                )
                VALUES (%s, %s, %s, %s::jsonb, %s)
            """,
                (
                    event_id,
                    order_id,
                    "order.created",
                    json.dumps(event_payload),
                    "PENDING",
                ),
            )

        conn.commit()

    log_structured(
        "order_created",
        event_type="order.created",
        order_id=order_id,
        status=order["status"],
        result="queued",
        idempotency_key=idempotency_key,
        outbox_event_id=event_id,
        outbox_status="PENDING",
    )

    return {**order, "message": "Order stored and outbox event queued successfully"}


@app.get("/orders/{order_id}", response_model=OrderResponse)
def get_order(order_id: str):
    with get_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT order_id, customer_id, sku, quantity, amount, currency, status
                FROM orders
                WHERE order_id = %s
            """,
                (order_id,),
            )
            order = cur.fetchone()

    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    return {**order, "message": "Order fetched successfully"}


@app.get("/workflows/{order_id}", response_model=WorkflowStateResponse)
def get_workflow(order_id: str):
    with get_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT
                    order_id,
                    current_step,
                    order_status,
                    inventory_status,
                    payment_status,
                    shipment_status
                FROM workflow_state
                WHERE order_id = %s
            """,
                (order_id,),
            )
            workflow = cur.fetchone()

    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow state not found")

    return workflow


@app.get("/outbox/pending", response_model=list[OutboxEventResponse])
def get_pending_outbox_events():
    with get_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("""
                SELECT
                    event_id,
                    aggregate_id,
                    event_type,
                    payload,
                    status,
                    created_at
                FROM outbox_events
                WHERE status = 'PENDING'
                ORDER BY created_at ASC
            """)
            events = cur.fetchall()

    return events
