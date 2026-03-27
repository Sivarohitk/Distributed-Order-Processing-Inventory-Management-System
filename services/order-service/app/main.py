import logging
from uuid import uuid4
from fastapi import FastAPI, Header, HTTPException
from .schemas import OrderCreate, OrderResponse

app = FastAPI(title="Order Service", version="0.1.0")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Temporary in-memory stores
orders_by_id = {}
orders_by_idempotency_key = {}


@app.get("/health")
def health():
    return {"status": "ok", "service": "order-service"}


@app.post("/orders", response_model=OrderResponse)
def create_order(payload: OrderCreate, idempotency_key: str = Header(default=None, alias="Idempotency-Key")):
    if not idempotency_key:
        raise HTTPException(status_code=400, detail="Idempotency-Key header is required")

    # Return the same order if the same idempotency key is reused
    if idempotency_key in orders_by_idempotency_key:
        existing_order = orders_by_idempotency_key[idempotency_key]
        logger.info("Duplicate request received for idempotency key %s", idempotency_key)
        return existing_order

    order_id = str(uuid4())

    order = {
        "order_id": order_id,
        "customer_id": payload.customer_id,
        "sku": payload.sku,
        "quantity": payload.quantity,
        "amount": payload.amount,
        "currency": payload.currency.upper(),
        "status": "PENDING",
        "message": "Order created successfully"
    }

    orders_by_id[order_id] = order
    orders_by_idempotency_key[idempotency_key] = order

    logger.info("Created order %s for customer %s", order_id, payload.customer_id)

    return order