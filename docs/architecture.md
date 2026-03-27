# Architecture Notes

See also:
- [Repository README](../README.md)
- [Workflow Diagrams](workflow-diagrams.md)

## Overview

This system models a distributed order lifecycle using multiple FastAPI services and a PostgreSQL-backed outbox workflow.

The current implementation favors demo simplicity over strict isolation:

- all services share one PostgreSQL instance
- all workflow events live in one shared `outbox_events` table
- downstream progression is triggered by polling `/events/process` endpoints instead of a message broker

## Service Responsibilities

### `order-service`

Responsible for:

- order intake
- idempotency enforcement via `Idempotency-Key`
- order persistence in `orders`
- workflow initialization in `workflow_state`
- `order.created` event creation in `outbox_events`

### `inventory-service`

Responsible for:

- seeding demo stock on startup
- stock lookup via `inventory_stock`
- reservation persistence in `inventory_reservations`
- consuming `order.created`
- emitting `inventory.reserved` or `inventory.failed`

### `payment-service`

Responsible for:

- payment persistence in `payments`
- consuming `inventory.reserved`
- applying the current demo authorization rule: amounts `<= 500` succeed
- emitting `payment.authorized` or `payment.failed`

### `shipment-service`

Responsible for:

- shipment persistence in `shipments`
- consuming `payment.authorized`
- emitting `shipment.created`

### `dispatcher-service`

Responsible for:

- polling the downstream service `/events/process` endpoints on a background loop
- exposing `POST /dispatch/run-once` for manual execution
- reporting last-run status at `GET /health`

## Data Model

### Shared Tables

- `orders`: created by `order-service` and used as the primary order record
- `workflow_state`: created by `order-service` and used as the workflow read model
- `outbox_events`: created by `order-service` and used by all consuming services

### Service-Specific Tables

- `inventory_stock`: created by `inventory-service` and seeded with three demo SKUs
- `inventory_reservations`: created by `inventory-service`
- `payments`: created by `payment-service`
- `shipments`: created by `shipment-service`

## Event Flow

### Happy Path

1. `order-service` stores an order and emits `order.created`.
2. `inventory-service` processes `order.created`, reserves stock, and emits `inventory.reserved`.
3. `payment-service` processes `inventory.reserved`, authorizes payment, and emits `payment.authorized`.
4. `shipment-service` processes `payment.authorized`, creates a shipment, and emits `shipment.created`.
5. `workflow_state.current_step` reaches `SHIPMENT_CREATED`.

### Failure Paths

- If stock is unavailable, `inventory-service` emits `inventory.failed` and sets `workflow_state.current_step` to `INVENTORY_REJECTED`.
- If payment amount is greater than `500`, `payment-service` emits `payment.failed` and sets `workflow_state.current_step` to `PAYMENT_FAILED`.

### Dispatcher Behavior

The dispatcher processes services in this order on each loop:

1. `inventory-service`
2. `payment-service`
3. `shipment-service`

That ordering matches the current event chain:

- `inventory-service` looks for pending `order.created`
- `payment-service` looks for pending `inventory.reserved`
- `shipment-service` looks for pending `payment.authorized`

## Reliability Model

### Idempotent Order Creation

`order-service` requires the `Idempotency-Key` header and returns the existing order if the same key is submitted again.

### Transactional Outbox

`order-service` writes the order row, workflow row, and initial outbox row in the same database transaction.

### Retry-Friendly Consumption

Each consuming service selects pending events with `FOR UPDATE SKIP LOCKED`, processes them, and then marks the consumed event as `PROCESSED`.

## Current Architectural Constraints

These are part of the implementation today and are important for accurate documentation:

- `payment-service` reads `amount` and `currency` directly from the shared `orders` table instead of using only the event payload.
- `workflow_state` is the most complete view of lifecycle progress; `orders.status` is initialized to `PENDING` and is not updated by downstream services.
- `inventory.failed`, `payment.failed`, and `shipment.created` are emitted into `outbox_events`, but no downstream processor consumes them.
- startup ordering depends on container timing because Compose currently uses `depends_on` without service health checks

## Future Improvements

Accurate future improvements for the current codebase include:

- add Compose health checks and health-based startup ordering
- make `orders.status` consistent with `workflow_state`, or reduce duplicate status storage
- move from a shared outbox table to explicit per-service messaging or a broker such as Kafka or RabbitMQ
- add explicit retry, backoff, and dead-letter handling for failed event processing
- add metrics and tracing for service-level observability
