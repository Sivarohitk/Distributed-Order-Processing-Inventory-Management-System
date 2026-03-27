# Distributed Order Processing & Inventory Management System

A microservices-based backend system that simulates order creation, inventory reservation, payment authorization, shipment creation, and asynchronous workflow progression using a PostgreSQL-backed transactional outbox pattern.

## Features

- Microservices-based design with clear service boundaries
- Idempotent order creation using `Idempotency-Key`
- PostgreSQL-backed persistence
- Transactional outbox pattern for reliable event creation
- Workflow state tracking across services
- Automated dispatcher/poller service for event progression
- Docker Compose support for full local startup
- End-to-end tests for happy path and failure scenarios

## Tech Stack

- Python
- FastAPI
- PostgreSQL
- Docker / Docker Compose
- Pytest
- HTTPX

## Services

- **order-service**
  - Accepts orders
  - Stores orders in PostgreSQL
  - Creates workflow state
  - Publishes `order.created` outbox events

- **inventory-service**
  - Consumes `order.created`
  - Reserves stock or rejects the order if stock is insufficient
  - Publishes `inventory.reserved` or `inventory.failed`

- **payment-service**
  - Consumes `inventory.reserved`
  - Simulates payment authorization
  - Publishes `payment.authorized` or `payment.failed`

- **shipment-service**
  - Consumes `payment.authorized`
  - Creates shipment records
  - Publishes `shipment.created`

- **dispatcher-service**
  - Polls downstream service event-processing endpoints automatically
  - Advances the workflow without manual triggering

## Workflow

Happy path:

1. Client creates order
2. `order-service` saves order and emits `order.created`
3. `inventory-service` reserves stock and emits `inventory.reserved`
4. `payment-service` authorizes payment and emits `payment.authorized`
5. `shipment-service` creates shipment and emits `shipment.created`
6. Workflow state becomes completed

Failure paths supported:

- Inventory failure when stock is insufficient
- Payment failure when amount is greater than the configured demo threshold

## Architecture Notes

This project uses a simplified **transactional outbox pattern**:
- business state and event records are written in the same database transaction
- downstream services process pending events
- workflow progress is stored in a shared `workflow_state` table for visibility

For local demo simplicity, services share one PostgreSQL database.
In a production-grade version, this could evolve into separate databases plus a broker such as Kafka or RabbitMQ.

## Project Structure

```text
.
├── docker-compose.yml
├── requirements-test.txt
├── docs/
├── services/
│   ├── order-service/
│   ├── inventory-service/
│   ├── payment-service/
│   ├── shipment-service/
│   └── dispatcher-service/
└── tests/