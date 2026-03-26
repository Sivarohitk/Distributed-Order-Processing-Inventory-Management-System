# Architecture

## Services
- Order Service
- Inventory Service
- Payment Service
- Shipment Service

## Communication Model
For the first version, services will communicate through database-backed events/outbox polling.
This keeps the project simple while still demonstrating distributed workflow design.

## Data Ownership
Each service owns its workflow logic.
PostgreSQL is used to persist:
- orders
- workflow state
- outbox/inbox events

## Reliability Features
- idempotency key for order creation
- retry-safe event handling
- health endpoints
- structured logs