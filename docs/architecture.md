# Architecture

## Overview

This system models a distributed order lifecycle using multiple FastAPI services and a PostgreSQL-backed event/outbox workflow.

## Services

### Order Service
Responsible for:
- order intake
- idempotency handling
- order persistence
- workflow initialization
- `order.created` event creation

### Inventory Service
Responsible for:
- stock lookup
- stock reservation
- inventory reservation persistence
- emitting `inventory.reserved` or `inventory.failed`

### Payment Service
Responsible for:
- payment simulation
- payment persistence
- emitting `payment.authorized` or `payment.failed`

### Shipment Service
Responsible for:
- shipment creation
- shipment persistence
- emitting `shipment.created`

### Dispatcher Service
Responsible for:
- polling service event-processing endpoints
- advancing the workflow automatically

## Data Model

### orders
Stores incoming order requests and order-level status.

### workflow_state
Tracks end-to-end lifecycle state:
- current step
- order status
- inventory status
- payment status
- shipment status

### outbox_events
Stores pending domain events for downstream processing.

### inventory_stock
Stores available stock by SKU.

### inventory_reservations
Stores reservation results per order.

### payments
Stores payment results per order.

### shipments
Stores shipment records per order.

## Event Flow

- `order.created`
- `inventory.reserved` or `inventory.failed`
- `payment.authorized` or `payment.failed`
- `shipment.created`

## Reliability Approach

### Idempotency
Order creation requires an `Idempotency-Key` header to prevent duplicate order creation.

### Transactional Outbox
The order record, workflow state, and initial event are written in a single transaction.

### Retry-Friendly Consumption
Services process pending events and mark them as processed after successful handling.

## Local Simplifications

To keep the demo understandable:
- all services share one PostgreSQL instance
- dispatcher uses polling
- services expose manual `/events/process` endpoints

## Future Improvements

- add message broker integration
- add healthcheck-based Compose startup ordering
- add CI workflow for tests
- add metrics and tracing
- split into separate service databases