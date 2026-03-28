import json
import logging
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Query
from psycopg.rows import dict_row

from .db import get_connection, init_db
from .schemas import (
    ProcessedShipmentEventResult,
    ProcessShipmentEventsResponse,
    ShipmentResponse,
)

app = FastAPI(title="Shipment Service", version="0.1.0")

SERVICE_NAME = "shipment-service"

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


@app.get("/shipments/{order_id}", response_model=ShipmentResponse)
def get_shipment(order_id: str):
    with get_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT shipment_id, order_id, status
                FROM shipments
                WHERE order_id = %s
            """,
                (order_id,),
            )
            shipment = cur.fetchone()

    if not shipment:
        raise HTTPException(status_code=404, detail="Shipment not found")

    return shipment


@app.post("/events/process", response_model=ProcessShipmentEventsResponse)
def process_payment_authorized_events(batch_size: int = Query(default=10, ge=1, le=100)):
    results: list[ProcessedShipmentEventResult] = []
    log_entries = []

    with get_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT event_id, aggregate_id, payload
                FROM outbox_events
                WHERE status = 'PENDING'
                  AND event_type = 'payment.authorized'
                ORDER BY created_at ASC
                FOR UPDATE SKIP LOCKED
                LIMIT %s
            """,
                (batch_size,),
            )
            events = cur.fetchall()

            for event in events:
                event_id = event["event_id"]
                order_id = event["aggregate_id"]

                cur.execute(
                    """
                    SELECT shipment_id, order_id, status
                    FROM shipments
                    WHERE order_id = %s
                """,
                    (order_id,),
                )
                existing_shipment = cur.fetchone()

                if existing_shipment:
                    cur.execute(
                        """
                        UPDATE outbox_events
                        SET status = 'PROCESSED',
                            published_at = CURRENT_TIMESTAMP
                        WHERE event_id = %s
                    """,
                        (event_id,),
                    )

                    results.append(
                        ProcessedShipmentEventResult(
                            event_id=event_id, order_id=order_id, result="ALREADY_SHIPPED"
                        )
                    )

                    log_entries.append(
                        {
                            "action": "payment_authorized_processed",
                            "event_type": "payment.authorized",
                            "order_id": order_id,
                            "status": existing_shipment["status"],
                            "result": "already_shipped",
                        }
                    )
                    continue

                shipment_id = str(uuid4())
                next_event_id = str(uuid4())

                cur.execute(
                    """
                    INSERT INTO shipments (
                        shipment_id,
                        order_id,
                        status
                    )
                    VALUES (%s, %s, %s)
                """,
                    (shipment_id, order_id, "CREATED"),
                )

                cur.execute(
                    """
                    UPDATE orders
                    SET status = %s
                    WHERE order_id = %s
                """,
                    ("COMPLETED", order_id),
                )

                cur.execute(
                    """
                    UPDATE workflow_state
                    SET current_step = %s,
                        order_status = %s,
                        shipment_status = %s,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE order_id = %s
                """,
                    ("SHIPMENT_CREATED", "COMPLETED", "CREATED", order_id),
                )

                next_payload = {"order_id": order_id, "shipment_status": "CREATED"}

                cur.execute(
                    """
                    INSERT INTO outbox_events (
                        event_id,
                        aggregate_id,
                        event_type,
                        payload,
                        status,
                        published_at
                    )
                    VALUES (%s, %s, %s, %s::jsonb, %s, CURRENT_TIMESTAMP)
                """,
                    (
                        next_event_id,
                        order_id,
                        "shipment.created",
                        json.dumps(next_payload),
                        "PROCESSED",
                    ),
                )

                cur.execute(
                    """
                    UPDATE outbox_events
                    SET status = 'PROCESSED',
                        published_at = CURRENT_TIMESTAMP
                    WHERE event_id = %s
                """,
                    (event_id,),
                )

                results.append(
                    ProcessedShipmentEventResult(
                        event_id=event_id, order_id=order_id, result="CREATED"
                    )
                )

                log_entries.append(
                    {
                        "action": "shipment_created",
                        "event_type": "payment.authorized",
                        "next_event_type": "shipment.created",
                        "order_id": order_id,
                        "status": "CREATED",
                        "result": "created",
                    }
                )

        conn.commit()

    for entry in log_entries:
        log_structured(**entry)

    log_structured(
        "event_batch_processed",
        event_type="payment.authorized",
        status="completed",
        processed_count=len(results),
        batch_size=batch_size,
    )

    return ProcessShipmentEventsResponse(processed_count=len(results), results=results)
