# Distributed Order Processing & Inventory Management System

A microservices-based backend system for handling order creation, inventory reservation, payment processing, and shipment lifecycle updates.

## Tech Stack
- Python
- FastAPI
- PostgreSQL
- Docker / Docker Compose

## Core Services
- **order-service**: accepts orders and starts the workflow
- **inventory-service**: reserves and releases stock
- **payment-service**: simulates payment authorization
- **shipment-service**: simulates shipment creation and status updates

## Key Design Goals
- Idempotent order APIs
- Async event-driven workflow
- PostgreSQL-backed workflow state
- Structured logging
- Health checks
- Service boundaries that are easy to test

## Planned Workflow
1. Client creates order
2. Order service stores order and emits event
3. Inventory service reserves stock
4. Payment service processes payment
5. Shipment service creates shipment
6. Order state is updated across the workflow

## Project Status
Initial scaffold in progress.