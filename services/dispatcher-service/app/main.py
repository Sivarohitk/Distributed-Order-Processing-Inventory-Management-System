import json
import logging
import os
import threading
from typing import Any

import httpx
from fastapi import FastAPI

SERVICE_NAME = "dispatcher-service"

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


INVENTORY_SERVICE_URL = os.getenv("INVENTORY_SERVICE_URL", "http://127.0.0.1:8002")
PAYMENT_SERVICE_URL = os.getenv("PAYMENT_SERVICE_URL", "http://127.0.0.1:8003")
SHIPMENT_SERVICE_URL = os.getenv("SHIPMENT_SERVICE_URL", "http://127.0.0.1:8004")
POLL_INTERVAL_SECONDS = int(os.getenv("POLL_INTERVAL_SECONDS", "5"))
BATCH_SIZE = int(os.getenv("BATCH_SIZE", "10"))

app = FastAPI(title="Dispatcher Service", version="0.1.0")

stop_event = threading.Event()
worker_thread = None
last_run_summary: dict[str, Any] = {"status": "not_started"}


def process_service_events(service_name: str, base_url: str) -> dict[str, Any]:
    url = f"{base_url}/events/process"
    try:
        with httpx.Client(timeout=10.0) as client:
            response = client.post(url, params={"batch_size": BATCH_SIZE})
            response.raise_for_status()
            data = response.json()

        log_structured(
            "dispatch_service_call",
            target_service=service_name,
            status="ok",
            result="completed",
            processed_count=data.get("processed_count"),
            batch_size=BATCH_SIZE,
        )
        return {"service": service_name, "ok": True, "response": data}
    except Exception as exc:
        log_exception(
            "dispatch_service_call_failed",
            target_service=service_name,
            status="error",
            result="request_failed",
        )
        return {"service": service_name, "ok": False, "error": str(exc)}


def dispatch_once() -> dict[str, Any]:
    summary = {
        "status": "completed",
        "results": [
            process_service_events("inventory-service", INVENTORY_SERVICE_URL),
            process_service_events("payment-service", PAYMENT_SERVICE_URL),
            process_service_events("shipment-service", SHIPMENT_SERVICE_URL),
        ],
    }
    successful_services = sum(1 for result in summary["results"] if result["ok"])
    log_structured(
        "dispatch_cycle_completed",
        status=summary["status"],
        successful_services=successful_services,
        total_services=len(summary["results"]),
    )
    return summary


def dispatcher_loop():
    global last_run_summary

    log_structured(
        "dispatcher_loop_started",
        status="running",
        poll_interval_seconds=POLL_INTERVAL_SECONDS,
        batch_size=BATCH_SIZE,
    )
    while not stop_event.is_set():
        try:
            last_run_summary = dispatch_once()
        except Exception as exc:
            log_exception("dispatcher_loop_failed", status="error")
            last_run_summary = {"status": "failed", "error": str(exc)}

        stop_event.wait(POLL_INTERVAL_SECONDS)

    log_structured("dispatcher_loop_stopped", status="stopped")


@app.on_event("startup")
def startup_event():
    global worker_thread

    stop_event.clear()
    worker_thread = threading.Thread(target=dispatcher_loop, daemon=True)
    worker_thread.start()
    log_structured(
        "startup_complete",
        status="ready",
        poll_interval_seconds=POLL_INTERVAL_SECONDS,
        batch_size=BATCH_SIZE,
    )


@app.on_event("shutdown")
def shutdown_event():
    stop_event.set()
    if worker_thread and worker_thread.is_alive():
        worker_thread.join(timeout=2)
    log_structured("shutdown_complete", status="stopped")


@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "dispatcher-service",
        "poll_interval_seconds": POLL_INTERVAL_SECONDS,
        "last_run_summary": last_run_summary,
    }


@app.post("/dispatch/run-once")
def run_once():
    global last_run_summary
    last_run_summary = dispatch_once()
    return last_run_summary
