import json
import os
import time
import urllib.error
import urllib.request
import uuid

ORDER_SERVICE_URL = os.getenv("ORDER_SERVICE_URL", "http://127.0.0.1:8001")
DISPATCHER_SERVICE_URL = os.getenv(
    "DISPATCHER_SERVICE_URL",
    "http://dispatcher-service:8005",
)
SHIPMENT_SERVICE_URL = os.getenv(
    "SHIPMENT_SERVICE_URL",
    "http://shipment-service:8004",
)
POLL_INTERVAL_SECONDS = float(os.getenv("POLL_INTERVAL_SECONDS", "2"))
TIMEOUT_SECONDS = float(os.getenv("TIMEOUT_SECONDS", "30"))
REQUEST_TIMEOUT_SECONDS = 10


def request_json(
    method: str,
    url: str,
    payload: dict | None = None,
    headers: dict[str, str] | None = None,
) -> dict:
    request_headers = {"Accept": "application/json"}
    if headers:
        request_headers.update(headers)

    body = None
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        request_headers["Content-Type"] = "application/json"

    request = urllib.request.Request(
        url,
        data=body,
        headers=request_headers,
        method=method,
    )

    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        details = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {url} failed with {exc.code}: {details}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"{method} {url} failed: {exc.reason}") from exc


def create_demo_order() -> dict:
    payload = {
        "customer_id": "demo-customer",
        "sku": "SKU-LAMP-01",
        "quantity": 1,
        "amount": 120.00,
        "currency": "usd",
    }
    idempotency_key = f"demo-{uuid.uuid4()}"

    return request_json(
        "POST",
        f"{ORDER_SERVICE_URL}/orders",
        payload=payload,
        headers={"Idempotency-Key": idempotency_key},
    )


def main() -> None:
    order = create_demo_order()
    order_id = order["order_id"]
    print(f"Order ID: {order_id}")

    deadline = time.time() + TIMEOUT_SECONDS
    workflow = None

    while time.time() < deadline:
        request_json("POST", f"{DISPATCHER_SERVICE_URL}/dispatch/run-once")
        workflow = request_json("GET", f"{ORDER_SERVICE_URL}/workflows/{order_id}")

        if workflow["current_step"] == "SHIPMENT_CREATED":
            break

        time.sleep(POLL_INTERVAL_SECONDS)
    else:
        raise RuntimeError(
            f"Timed out waiting for workflow completion for order {order_id}"
        )

    shipment = request_json("GET", f"{SHIPMENT_SERVICE_URL}/shipments/{order_id}")

    print()
    print("Final workflow state:")
    print(json.dumps(workflow, indent=2))

    print()
    print("Shipment:")
    print(json.dumps(shipment, indent=2))


if __name__ == "__main__":
    main()
