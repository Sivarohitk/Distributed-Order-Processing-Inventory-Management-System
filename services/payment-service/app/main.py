import json
import logging
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Query
from psycopg.rows import dict_row

from .db import get_connection, init_db
from .schemas import (
    PaymentResponse,
    ProcessedPaymentEventResult,
    ProcessPaymentEventsResponse,
)

app = FastAPI(title="Payment Service", version="0.1.0")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@app.on_event("startup")
def startup_event():
    init_db()
    logger.info("Payment database initialized")


@app.get("/health")
def health():
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()

        return {
            "status": "ok",
            "service": "payment-service",
            "database": "connected"
        }
    except Exception:
        logger.exception("Payment health check failed")
        raise HTTPException(status_code=503, detail="Database unavailable")


@app.get("/payments/{order_id}", response_model=PaymentResponse)
def get_payment(order_id: str):
    with get_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("""
                SELECT payment_id, order_id, amount, currency, status
                FROM payments
                WHERE order_id = %s
            """, (order_id,))
            payment = cur.fetchone()

    if not payment:
        raise HTTPException(status_code=404, detail="Payment not found")

    return payment


@app.post("/events/process", response_model=ProcessPaymentEventsResponse)
def process_inventory_reserved_events(
    batch_size: int = Query(default=10, ge=1, le=100)
):
    results: list[ProcessedPaymentEventResult] = []

    with get_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("""
                SELECT event_id, aggregate_id, payload
                FROM outbox_events
                WHERE status = 'PENDING'
                  AND event_type = 'inventory.reserved'
                ORDER BY created_at ASC
                FOR UPDATE SKIP LOCKED
                LIMIT %s
            """, (batch_size,))
            events = cur.fetchall()

            for event in events:
                event_id = event["event_id"]
                order_id = event["aggregate_id"]
                payload = event["payload"]

                cur.execute("""
                    SELECT payment_id, order_id, amount, currency, status
                    FROM payments
                    WHERE order_id = %s
                """, (order_id,))
                existing_payment = cur.fetchone()

                if existing_payment:
                    cur.execute("""
                        UPDATE outbox_events
                        SET status = 'PROCESSED',
                            published_at = CURRENT_TIMESTAMP
                        WHERE event_id = %s
                    """, (event_id,))

                    results.append(
                        ProcessedPaymentEventResult(
                            event_id=event_id,
                            order_id=order_id,
                            result="ALREADY_PROCESSED"
                        )
                    )
                    continue

                cur.execute("""
                    SELECT amount, currency
                    FROM orders
                    WHERE order_id = %s
                """, (order_id,))
                order_row = cur.fetchone()

                if not order_row:
                    cur.execute("""
                        UPDATE outbox_events
                        SET status = 'FAILED',
                            retry_count = retry_count + 1
                        WHERE event_id = %s
                    """, (event_id,))

                    results.append(
                        ProcessedPaymentEventResult(
                            event_id=event_id,
                            order_id=order_id,
                            result="ORDER_NOT_FOUND"
                        )
                    )
                    continue

                payment_id = str(uuid4())
                next_event_id = str(uuid4())
                amount = order_row["amount"]
                currency = order_row["currency"]

                # Simple demo rule:
                # payments <= 500 succeed, > 500 fail
                if float(amount) <= 500:
                    payment_status = "AUTHORIZED"
                    next_event_type = "payment.authorized"
                    workflow_step = "PAYMENT_AUTHORIZED"

                    cur.execute("""
                        UPDATE workflow_state
                        SET current_step = %s,
                            payment_status = %s,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE order_id = %s
                    """, (
                        workflow_step,
                        payment_status,
                        order_id
                    ))
                else:
                    payment_status = "FAILED"
                    next_event_type = "payment.failed"
                    workflow_step = "PAYMENT_FAILED"

                    cur.execute("""
                        UPDATE workflow_state
                        SET current_step = %s,
                            order_status = %s,
                            payment_status = %s,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE order_id = %s
                    """, (
                        workflow_step,
                        "FAILED",
                        payment_status,
                        order_id
                    ))

                cur.execute("""
                    INSERT INTO payments (
                        payment_id,
                        order_id,
                        amount,
                        currency,
                        status
                    )
                    VALUES (%s, %s, %s, %s, %s)
                """, (
                    payment_id,
                    order_id,
                    amount,
                    currency,
                    payment_status
                ))

                next_payload = {
                    "order_id": order_id,
                    "payment_status": payment_status,
                    "amount": float(amount),
                    "currency": currency
                }

                cur.execute("""
                    INSERT INTO outbox_events (
                        event_id,
                        aggregate_id,
                        event_type,
                        payload,
                        status
                    )
                    VALUES (%s, %s, %s, %s::jsonb, %s)
                """, (
                    next_event_id,
                    order_id,
                    next_event_type,
                    json.dumps(next_payload),
                    "PENDING"
                ))

                cur.execute("""
                    UPDATE outbox_events
                    SET status = 'PROCESSED',
                        published_at = CURRENT_TIMESTAMP
                    WHERE event_id = %s
                """, (event_id,))

                results.append(
                    ProcessedPaymentEventResult(
                        event_id=event_id,
                        order_id=order_id,
                        result=payment_status
                    )
                )

        conn.commit()

    logger.info("Processed %s inventory.reserved events", len(results))

    return ProcessPaymentEventsResponse(
        processed_count=len(results),
        results=results
    )