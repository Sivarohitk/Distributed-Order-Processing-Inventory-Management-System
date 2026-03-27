import json
import logging
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Query
from psycopg.rows import dict_row

from .db import get_connection, init_db
from .schemas import (
    ShipmentResponse,
    ProcessedShipmentEventResult,
    ProcessShipmentEventsResponse,
)

app = FastAPI(title="Shipment Service", version="0.1.0")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@app.on_event("startup")
def startup_event():
    init_db()
    logger.info("Shipment database initialized")


@app.get("/health")
def health():
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()

        return {
            "status": "ok",
            "service": "shipment-service",
            "database": "connected"
        }
    except Exception:
        logger.exception("Shipment health check failed")
        raise HTTPException(status_code=503, detail="Database unavailable")


@app.get("/shipments/{order_id}", response_model=ShipmentResponse)
def get_shipment(order_id: str):
    with get_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("""
                SELECT shipment_id, order_id, status
                FROM shipments
                WHERE order_id = %s
            """, (order_id,))
            shipment = cur.fetchone()

    if not shipment:
        raise HTTPException(status_code=404, detail="Shipment not found")

    return shipment


@app.post("/events/process", response_model=ProcessShipmentEventsResponse)
def process_payment_authorized_events(
    batch_size: int = Query(default=10, ge=1, le=100)
):
    results: list[ProcessedShipmentEventResult] = []

    with get_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("""
                SELECT event_id, aggregate_id, payload
                FROM outbox_events
                WHERE status = 'PENDING'
                  AND event_type = 'payment.authorized'
                ORDER BY created_at ASC
                FOR UPDATE SKIP LOCKED
                LIMIT %s
            """, (batch_size,))
            events = cur.fetchall()

            for event in events:
                event_id = event["event_id"]
                order_id = event["aggregate_id"]

                cur.execute("""
                    SELECT shipment_id, order_id, status
                    FROM shipments
                    WHERE order_id = %s
                """, (order_id,))
                existing_shipment = cur.fetchone()

                if existing_shipment:
                    cur.execute("""
                        UPDATE outbox_events
                        SET status = 'PROCESSED',
                            published_at = CURRENT_TIMESTAMP
                        WHERE event_id = %s
                    """, (event_id,))

                    results.append(
                        ProcessedShipmentEventResult(
                            event_id=event_id,
                            order_id=order_id,
                            result="ALREADY_SHIPPED"
                        )
                    )
                    continue

                shipment_id = str(uuid4())
                next_event_id = str(uuid4())

                cur.execute("""
                    INSERT INTO shipments (
                        shipment_id,
                        order_id,
                        status
                    )
                    VALUES (%s, %s, %s)
                """, (
                    shipment_id,
                    order_id,
                    "CREATED"
                ))

                cur.execute("""
                    UPDATE workflow_state
                    SET current_step = %s,
                        order_status = %s,
                        shipment_status = %s,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE order_id = %s
                """, (
                    "SHIPMENT_CREATED",
                    "COMPLETED",
                    "CREATED",
                    order_id
                ))

                next_payload = {
                    "order_id": order_id,
                    "shipment_status": "CREATED"
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
                    "shipment.created",
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
                    ProcessedShipmentEventResult(
                        event_id=event_id,
                        order_id=order_id,
                        result="CREATED"
                    )
                )

        conn.commit()

    logger.info("Processed %s payment.authorized events", len(results))

    return ProcessShipmentEventsResponse(
        processed_count=len(results),
        results=results
    )