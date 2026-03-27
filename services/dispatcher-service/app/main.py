import logging
import os
import threading
import time
from typing import Any

import httpx
from fastapi import FastAPI

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

INVENTORY_SERVICE_URL = os.getenv("INVENTORY_SERVICE_URL", "http://127.0.0.1:8002")
PAYMENT_SERVICE_URL = os.getenv("PAYMENT_SERVICE_URL", "http://127.0.0.1:8003")
SHIPMENT_SERVICE_URL = os.getenv("SHIPMENT_SERVICE_URL", "http://127.0.0.1:8004")
POLL_INTERVAL_SECONDS = int(os.getenv("POLL_INTERVAL_SECONDS", "5"))
BATCH_SIZE = int(os.getenv("BATCH_SIZE", "10"))

app = FastAPI(title="Dispatcher Service", version="0.1.0")

stop_event = threading.Event()
worker_thread = None
last_run_summary: dict[str, Any] = {
    "status": "not_started"
}


def process_service_events(service_name: str, base_url: str) -> dict[str, Any]:
    url = f"{base_url}/events/process"
    try:
        with httpx.Client(timeout=10.0) as client:
            response = client.post(url, params={"batch_size": BATCH_SIZE})
            response.raise_for_status()
            data = response.json()

        logger.info("%s processed events: %s", service_name, data)
        return {
            "service": service_name,
            "ok": True,
            "response": data
        }
    except Exception as exc:
        logger.exception("Dispatcher failed calling %s", service_name)
        return {
            "service": service_name,
            "ok": False,
            "error": str(exc)
        }


def dispatch_once() -> dict[str, Any]:
    summary = {
        "status": "completed",
        "results": [
            process_service_events("inventory-service", INVENTORY_SERVICE_URL),
            process_service_events("payment-service", PAYMENT_SERVICE_URL),
            process_service_events("shipment-service", SHIPMENT_SERVICE_URL),
        ]
    }
    return summary


def dispatcher_loop():
    global last_run_summary

    logger.info("Dispatcher loop started")
    while not stop_event.is_set():
        try:
            last_run_summary = dispatch_once()
        except Exception as exc:
            logger.exception("Unexpected dispatcher loop failure")
            last_run_summary = {
                "status": "failed",
                "error": str(exc)
            }

        stop_event.wait(POLL_INTERVAL_SECONDS)

    logger.info("Dispatcher loop stopped")


@app.on_event("startup")
def startup_event():
    global worker_thread

    stop_event.clear()
    worker_thread = threading.Thread(target=dispatcher_loop, daemon=True)
    worker_thread.start()
    logger.info("Dispatcher service started")


@app.on_event("shutdown")
def shutdown_event():
    stop_event.set()
    if worker_thread and worker_thread.is_alive():
        worker_thread.join(timeout=2)
    logger.info("Dispatcher service stopped")


@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "dispatcher-service",
        "poll_interval_seconds": POLL_INTERVAL_SECONDS,
        "last_run_summary": last_run_summary
    }


@app.post("/dispatch/run-once")
def run_once():
    global last_run_summary
    last_run_summary = dispatch_once()
    return last_run_summary