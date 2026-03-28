import os
import time
import uuid

import httpx
import psycopg

DISPATCHER_SERVICE_URL = os.getenv("DISPATCHER_SERVICE_URL", "http://127.0.0.1:8005")
ORDER_SERVICE_URL = os.getenv("ORDER_SERVICE_URL", "http://127.0.0.1:8001")
INVENTORY_SERVICE_URL = os.getenv("INVENTORY_SERVICE_URL", "http://127.0.0.1:8002")
PAYMENT_SERVICE_URL = os.getenv("PAYMENT_SERVICE_URL", "http://127.0.0.1:8003")
SHIPMENT_SERVICE_URL = os.getenv("SHIPMENT_SERVICE_URL", "http://127.0.0.1:8004")
REQUEST_TIMEOUT_SECONDS = 10.0
TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql://postgres:postgres@127.0.0.1:5432/order_db",
)


def request(method: str, url: str, **kwargs):
    with httpx.Client(timeout=REQUEST_TIMEOUT_SECONDS, trust_env=False) as client:
        return client.request(method, url, **kwargs)


def create_order(
    sku: str,
    quantity: int,
    amount: float,
    *,
    idempotency_key: str | None = None,
    customer_id: str | None = None,
):
    idempotency_key = idempotency_key or f"test-{uuid.uuid4()}"
    payload = {
        "customer_id": customer_id or f"cust-{uuid.uuid4()}",
        "sku": sku,
        "quantity": quantity,
        "amount": amount,
        "currency": "usd",
    }

    response = request(
        "POST",
        f"{ORDER_SERVICE_URL}/orders",
        headers={"Idempotency-Key": idempotency_key},
        json=payload,
    )
    response.raise_for_status()
    return response.json()


def get_order(order_id: str):
    response = request("GET", f"{ORDER_SERVICE_URL}/orders/{order_id}")
    response.raise_for_status()
    return response.json()


def get_workflow(order_id: str):
    response = request("GET", f"{ORDER_SERVICE_URL}/workflows/{order_id}")
    response.raise_for_status()
    return response.json()


def get_pending_outbox_events():
    response = request("GET", f"{ORDER_SERVICE_URL}/outbox/pending")
    response.raise_for_status()
    return response.json()


def process_inventory_events(batch_size: int = 10):
    response = request(
        "POST",
        f"{INVENTORY_SERVICE_URL}/events/process",
        params={"batch_size": batch_size},
    )
    response.raise_for_status()
    return response.json()


def process_payment_events(batch_size: int = 10):
    response = request(
        "POST",
        f"{PAYMENT_SERVICE_URL}/events/process",
        params={"batch_size": batch_size},
    )
    response.raise_for_status()
    return response.json()


def get_shipment(order_id: str):
    response = request("GET", f"{SHIPMENT_SERVICE_URL}/shipments/{order_id}")
    return response


def get_payment(order_id: str):
    response = request("GET", f"{PAYMENT_SERVICE_URL}/payments/{order_id}")
    return response


def dispatch_run_once():
    response = request("POST", f"{DISPATCHER_SERVICE_URL}/dispatch/run-once")
    response.raise_for_status()
    return response.json()


def create_order_with_pending_work(sku: str, quantity: int, amount: float):
    for _ in range(3):
        order = create_order(sku=sku, quantity=quantity, amount=amount)
        workflow = get_workflow(order["order_id"])
        if workflow["current_step"] == "ORDER_CREATED":
            return order, workflow
        time.sleep(0.5)

    raise AssertionError(
        "Could not create an order before the background dispatcher picked it up"
    )


def wait_for_workflow_step(order_id: str, expected_step: str, timeout_seconds: int = 30):
    deadline = time.time() + timeout_seconds

    while time.time() < deadline:
        workflow = get_workflow(order_id)
        if workflow["current_step"] == expected_step:
            return workflow
        time.sleep(1)

    raise AssertionError(
        f"Workflow for order {order_id} did not reach {expected_step} within {timeout_seconds} seconds"
    )


def assert_no_pending_outbox_events_for_order(order_id: str):
    pending_events = get_pending_outbox_events()
    assert not any(
        event["aggregate_id"] == order_id
        for event in pending_events
    )


def update_order_amount_and_currency(order_id: str, amount: float, currency: str):
    with psycopg.connect(TEST_DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE orders
                SET amount = %s,
                    currency = %s
                WHERE order_id = %s
            """, (amount, currency, order_id))
        conn.commit()


def test_idempotent_order_creation_returns_the_same_order():
    idempotency_key = f"idempotency-{uuid.uuid4()}"
    customer_id = f"cust-{uuid.uuid4()}"

    first_order = create_order(
        sku="SKU-LAMP-01",
        quantity=1,
        amount=75.00,
        idempotency_key=idempotency_key,
        customer_id=customer_id,
    )
    second_order = create_order(
        sku="SKU-LAMP-01",
        quantity=1,
        amount=75.00,
        idempotency_key=idempotency_key,
        customer_id=customer_id,
    )

    assert first_order["message"] == "Order stored and outbox event queued successfully"
    assert second_order["message"] == "Order already exists for this idempotency key"
    assert second_order["order_id"] == first_order["order_id"]
    assert second_order["customer_id"] == first_order["customer_id"]
    assert second_order["sku"] == first_order["sku"]
    assert second_order["quantity"] == first_order["quantity"]
    assert second_order["amount"] == first_order["amount"]
    assert second_order["currency"] == first_order["currency"]
    assert second_order["status"] == "PENDING"

    stored_order = get_order(first_order["order_id"])
    assert stored_order["order_id"] == first_order["order_id"]
    assert stored_order["status"] == "PENDING"


def test_payment_service_uses_inventory_event_payload_instead_of_orders_table():
    for _ in range(3):
        order, workflow = create_order_with_pending_work(
            sku="SKU-LAMP-01",
            quantity=1,
            amount=80.00,
        )
        order_id = order["order_id"]

        assert workflow["current_step"] == "ORDER_CREATED"

        summary = process_inventory_events(batch_size=1)

        assert summary["processed_count"] in (0, 1)
        if get_payment(order_id).status_code == 404:
            break
        time.sleep(0.5)
    else:
        raise AssertionError(
            "Could not create an order before the background dispatcher processed payment"
        )

    update_order_amount_and_currency(order_id, 999.99, "EUR")

    payment_summary = process_payment_events(batch_size=1)
    assert payment_summary["processed_count"] in (0, 1)

    dispatch_run_once()
    workflow_after = wait_for_workflow_step(order_id, "SHIPMENT_CREATED", timeout_seconds=5)
    assert workflow_after["order_status"] == "COMPLETED"

    payment_response = get_payment(order_id)
    assert payment_response.status_code == 200

    payment = payment_response.json()
    assert payment["amount"] == order["amount"]
    assert payment["currency"] == order["currency"]
    assert payment["status"] == "AUTHORIZED"
    assert_no_pending_outbox_events_for_order(order_id)


def test_dispatch_run_once_advances_pending_work():
    order, workflow = create_order_with_pending_work(
        sku="SKU-LAMP-01",
        quantity=1,
        amount=80.00,
    )
    order_id = order["order_id"]

    assert workflow["current_step"] == "ORDER_CREATED"
    assert workflow["order_status"] == "PENDING"

    summary = dispatch_run_once()

    assert summary["status"] == "completed"
    assert len(summary["results"]) == 3
    assert all(result["ok"] for result in summary["results"])
    assert any(
        result["response"]["processed_count"] > 0
        for result in summary["results"]
    )

    workflow_after = wait_for_workflow_step(order_id, "SHIPMENT_CREATED", timeout_seconds=5)
    assert workflow_after["order_status"] == "COMPLETED"
    assert workflow_after["inventory_status"] == "RESERVED"
    assert workflow_after["payment_status"] == "AUTHORIZED"
    assert workflow_after["shipment_status"] == "CREATED"

    stored_order = get_order(order_id)
    assert stored_order["order_id"] == order_id
    assert stored_order["status"] == "COMPLETED"
    assert_no_pending_outbox_events_for_order(order_id)


def test_happy_path_order_to_shipment():
    order = create_order(sku="SKU-LAMP-01", quantity=2, amount=120.00)
    order_id = order["order_id"]

    assert order["status"] == "PENDING"

    workflow = wait_for_workflow_step(order_id, "SHIPMENT_CREATED")

    assert workflow["order_status"] == "COMPLETED"
    assert workflow["inventory_status"] == "RESERVED"
    assert workflow["payment_status"] == "AUTHORIZED"
    assert workflow["shipment_status"] == "CREATED"

    stored_order = get_order(order_id)
    assert stored_order["order_id"] == order_id
    assert stored_order["status"] == "COMPLETED"
    assert_no_pending_outbox_events_for_order(order_id)

    shipment_response = get_shipment(order_id)
    assert shipment_response.status_code == 200

    shipment = shipment_response.json()
    assert shipment["order_id"] == order_id
    assert shipment["status"] == "CREATED"


def test_inventory_failure_path():
    order = create_order(sku="SKU-TABLE-01", quantity=999, amount=149.99)
    order_id = order["order_id"]

    assert order["status"] == "PENDING"

    workflow = wait_for_workflow_step(order_id, "INVENTORY_REJECTED")

    assert workflow["order_status"] == "FAILED"
    assert workflow["inventory_status"] == "FAILED"
    assert workflow["payment_status"] == "NOT_STARTED"
    assert workflow["shipment_status"] == "NOT_STARTED"

    stored_order = get_order(order_id)
    assert stored_order["order_id"] == order_id
    assert stored_order["status"] == "FAILED"
    assert_no_pending_outbox_events_for_order(order_id)

    payment_response = get_payment(order_id)
    assert payment_response.status_code == 404

    shipment_response = get_shipment(order_id)
    assert shipment_response.status_code == 404


def test_payment_failure_path():
    order = create_order(sku="SKU-CHAIR-01", quantity=1, amount=999.99)
    order_id = order["order_id"]

    assert order["status"] == "PENDING"

    workflow = wait_for_workflow_step(order_id, "PAYMENT_FAILED")

    assert workflow["order_status"] == "FAILED"
    assert workflow["inventory_status"] == "RESERVED"
    assert workflow["payment_status"] == "FAILED"
    assert workflow["shipment_status"] == "NOT_STARTED"

    stored_order = get_order(order_id)
    assert stored_order["order_id"] == order_id
    assert stored_order["status"] == "FAILED"
    assert_no_pending_outbox_events_for_order(order_id)

    payment_response = get_payment(order_id)
    assert payment_response.status_code == 200

    payment = payment_response.json()
    assert payment["order_id"] == order_id
    assert payment["status"] == "FAILED"

    shipment_response = get_shipment(order_id)
    assert shipment_response.status_code == 404
