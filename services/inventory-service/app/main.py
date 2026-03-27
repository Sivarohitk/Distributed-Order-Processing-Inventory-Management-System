import json
import logging
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Query
from psycopg.rows import dict_row

from .db import get_connection, init_db
from .schemas import (
    InventoryReservationResponse,
    InventoryStockResponse,
    ProcessedEventResult,
    ProcessEventsResponse,
)

app = FastAPI(title="Inventory Service", version="0.1.0")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@app.on_event("startup")
def startup_event():
    init_db()
    logger.info("Inventory database initialized")


@app.get("/health")
def health():
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()

        return {
            "status": "ok",
            "service": "inventory-service",
            "database": "connected"
        }
    except Exception:
        logger.exception("Inventory health check failed")
        raise HTTPException(status_code=503, detail="Database unavailable")


@app.get("/inventory/{sku}", response_model=InventoryStockResponse)
def get_inventory(sku: str):
    with get_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("""
                SELECT sku, available_quantity
                FROM inventory_stock
                WHERE sku = %s
            """, (sku,))
            stock = cur.fetchone()

    if not stock:
        raise HTTPException(status_code=404, detail="SKU not found")

    return stock


@app.get("/reservations/{order_id}", response_model=InventoryReservationResponse)
def get_reservation(order_id: str):
    with get_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("""
                SELECT reservation_id, order_id, sku, quantity, status
                FROM inventory_reservations
                WHERE order_id = %s
            """, (order_id,))
            reservation = cur.fetchone()

    if not reservation:
        raise HTTPException(status_code=404, detail="Reservation not found")

    return reservation


@app.post("/events/process", response_model=ProcessEventsResponse)
def process_order_created_events(
    batch_size: int = Query(default=10, ge=1, le=100)
):
    results: list[ProcessedEventResult] = []

    with get_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("""
                SELECT event_id, aggregate_id, payload
                FROM outbox_events
                WHERE status = 'PENDING'
                  AND event_type = 'order.created'
                ORDER BY created_at ASC
                FOR UPDATE SKIP LOCKED
                LIMIT %s
            """, (batch_size,))
            events = cur.fetchall()

            for event in events:
                event_id = event["event_id"]
                order_id = event["aggregate_id"]
                payload = event["payload"]

                sku = payload["sku"]
                quantity = payload["quantity"]

                cur.execute("""
                    SELECT reservation_id, order_id, sku, quantity, status
                    FROM inventory_reservations
                    WHERE order_id = %s
                """, (order_id,))
                existing_reservation = cur.fetchone()

                if existing_reservation:
                    cur.execute("""
                        UPDATE outbox_events
                        SET status = 'PROCESSED',
                            published_at = CURRENT_TIMESTAMP
                        WHERE event_id = %s
                    """, (event_id,))

                    results.append(
                        ProcessedEventResult(
                            event_id=event_id,
                            order_id=order_id,
                            sku=sku,
                            quantity=quantity,
                            result="ALREADY_RESERVED"
                        )
                    )
                    continue

                cur.execute("""
                    SELECT sku, available_quantity
                    FROM inventory_stock
                    WHERE sku = %s
                    FOR UPDATE
                """, (sku,))
                stock = cur.fetchone()

                if stock and stock["available_quantity"] >= quantity:
                    new_available_quantity = stock["available_quantity"] - quantity
                    reservation_id = str(uuid4())
                    next_event_id = str(uuid4())

                    cur.execute("""
                        UPDATE inventory_stock
                        SET available_quantity = %s,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE sku = %s
                    """, (new_available_quantity, sku))

                    cur.execute("""
                        INSERT INTO inventory_reservations (
                            reservation_id,
                            order_id,
                            sku,
                            quantity,
                            status
                        )
                        VALUES (%s, %s, %s, %s, %s)
                    """, (
                        reservation_id,
                        order_id,
                        sku,
                        quantity,
                        "RESERVED"
                    ))

                    cur.execute("""
                        UPDATE workflow_state
                        SET current_step = %s,
                            inventory_status = %s,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE order_id = %s
                    """, (
                        "INVENTORY_RESERVED",
                        "RESERVED",
                        order_id
                    ))

                    reserved_payload = {
                        "order_id": order_id,
                        "sku": sku,
                        "quantity": quantity,
                        "inventory_status": "RESERVED"
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
                        "inventory.reserved",
                        json.dumps(reserved_payload),
                        "PENDING"
                    ))

                    cur.execute("""
                        UPDATE outbox_events
                        SET status = 'PROCESSED',
                            published_at = CURRENT_TIMESTAMP
                        WHERE event_id = %s
                    """, (event_id,))

                    results.append(
                        ProcessedEventResult(
                            event_id=event_id,
                            order_id=order_id,
                            sku=sku,
                            quantity=quantity,
                            result="RESERVED"
                        )
                    )

                else:
                    reservation_id = str(uuid4())
                    next_event_id = str(uuid4())

                    cur.execute("""
                        INSERT INTO inventory_reservations (
                            reservation_id,
                            order_id,
                            sku,
                            quantity,
                            status
                        )
                        VALUES (%s, %s, %s, %s, %s)
                    """, (
                        reservation_id,
                        order_id,
                        sku,
                        quantity,
                        "FAILED"
                    ))

                    cur.execute("""
                        UPDATE workflow_state
                        SET current_step = %s,
                            order_status = %s,
                            inventory_status = %s,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE order_id = %s
                    """, (
                        "INVENTORY_REJECTED",
                        "FAILED",
                        "FAILED",
                        order_id
                    ))

                    failed_payload = {
                        "order_id": order_id,
                        "sku": sku,
                        "quantity": quantity,
                        "inventory_status": "FAILED"
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
                        "inventory.failed",
                        json.dumps(failed_payload),
                        "PENDING"
                    ))

                    cur.execute("""
                        UPDATE outbox_events
                        SET status = 'PROCESSED',
                            published_at = CURRENT_TIMESTAMP
                        WHERE event_id = %s
                    """, (event_id,))

                    results.append(
                        ProcessedEventResult(
                            event_id=event_id,
                            order_id=order_id,
                            sku=sku,
                            quantity=quantity,
                            result="FAILED"
                        )
                    )

        conn.commit()

    logger.info("Processed %s order.created events", len(results))

    return ProcessEventsResponse(
        processed_count=len(results),
        results=results
    )