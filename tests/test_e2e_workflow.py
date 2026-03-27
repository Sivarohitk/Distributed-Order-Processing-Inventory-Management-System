import time
import uuid

import httpx

ORDER_SERVICE_URL = "http://127.0.0.1:8001"
INVENTORY_SERVICE_URL = "http://127.0.0.1:8002"
PAYMENT_SERVICE_URL = "http://127.0.0.1:8003"
SHIPMENT_SERVICE_URL = "http://127.0.0.1:8004"


def create_order(sku: str, quantity: int, amount: float):
    idempotency_key = f"test-{uuid.uuid4()}"
    payload = {
        "customer_id": f"cust-{uuid.uuid4()}",
        "sku": sku,
        "quantity": quantity,
        "amount": amount,
        "currency": "usd",
    }

    response = httpx.post(
        f"{ORDER_SERVICE_URL}/orders",
        headers={"Idempotency-Key": idempotency_key},
        json=payload,
        timeout=10.0,
    )
    response.raise_for_status()
    return response.json()


def get_workflow(order_id: str):
    response = httpx.get(f"{ORDER_SERVICE_URL}/workflows/{order_id}", timeout=10.0)
    response.raise_for_status()
    return response.json()


def get_shipment(order_id: str):
    response = httpx.get(f"{SHIPMENT_SERVICE_URL}/shipments/{order_id}", timeout=10.0)
    return response


def get_payment(order_id: str):
    response = httpx.get(f"{PAYMENT_SERVICE_URL}/payments/{order_id}", timeout=10.0)
    return response


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


def test_happy_path_order_to_shipment():
    order = create_order(sku="SKU-LAMP-01", quantity=2, amount=120.00)
    order_id = order["order_id"]

    workflow = wait_for_workflow_step(order_id, "SHIPMENT_CREATED")

    assert workflow["order_status"] == "COMPLETED"
    assert workflow["inventory_status"] == "RESERVED"
    assert workflow["payment_status"] == "AUTHORIZED"
    assert workflow["shipment_status"] == "CREATED"

    shipment_response = get_shipment(order_id)
    assert shipment_response.status_code == 200

    shipment = shipment_response.json()
    assert shipment["order_id"] == order_id
    assert shipment["status"] == "CREATED"


def test_inventory_failure_path():
    order = create_order(sku="SKU-TABLE-01", quantity=999, amount=149.99)
    order_id = order["order_id"]

    workflow = wait_for_workflow_step(order_id, "INVENTORY_REJECTED")

    assert workflow["order_status"] == "FAILED"
    assert workflow["inventory_status"] == "FAILED"
    assert workflow["payment_status"] == "NOT_STARTED"
    assert workflow["shipment_status"] == "NOT_STARTED"

    payment_response = get_payment(order_id)
    assert payment_response.status_code == 404

    shipment_response = get_shipment(order_id)
    assert shipment_response.status_code == 404


def test_payment_failure_path():
    order = create_order(sku="SKU-CHAIR-01", quantity=1, amount=999.99)
    order_id = order["order_id"]

    workflow = wait_for_workflow_step(order_id, "PAYMENT_FAILED")

    assert workflow["order_status"] == "FAILED"
    assert workflow["inventory_status"] == "RESERVED"
    assert workflow["payment_status"] == "FAILED"
    assert workflow["shipment_status"] == "NOT_STARTED"

    payment_response = get_payment(order_id)
    assert payment_response.status_code == 200

    payment = payment_response.json()
    assert payment["order_id"] == order_id
    assert payment["status"] == "FAILED"

    shipment_response = get_shipment(order_id)
    assert shipment_response.status_code == 404