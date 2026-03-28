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
2. `inventory-service` processes `order.created`, reserves stock, and emits `inventory.reserved` with the `amount` and `currency` needed for payment authorization.
3. `payment-service` processes `inventory.reserved`, uses the event payload for `amount` and `currency`, authorizes payment, and emits `payment.authorized`.
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

- services still share one database, but `payment-service` now uses `inventory.reserved` payload data instead of reading `amount` and `currency` from the shared `orders` table.
- `workflow_state` is still the most complete view of lifecycle progress; `orders.status` stays `PENDING` during in-flight work and is updated to `FAILED` or `COMPLETED` when the workflow reaches a terminal outcome.
- `inventory.failed`, `payment.failed`, and `shipment.created` are emitted into `outbox_events` for audit visibility, but they are inserted with a non-pending status because no downstream processor consumes them.

## Future Improvements

Accurate future improvements for the current codebase include:

- reduce duplicate status storage between `orders` and `workflow_state`, or define stricter ownership for each field
- move from a shared outbox table to explicit per-service messaging or a broker such as Kafka or RabbitMQ
- add explicit retry, backoff, and dead-letter handling for failed event processing
- add metrics and tracing for service-level observability
