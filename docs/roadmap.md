# Roadmap And Limitations

See also:
- [Repository README](../README.md)
- [Architecture Notes](architecture.md)
- [Workflow Diagrams](workflow-diagrams.md)

## Current Capabilities

The project currently demonstrates:

- five FastAPI services for order intake, inventory reservation, payment authorization, shipment creation, and event dispatching
- idempotent order creation through the `Idempotency-Key` header
- a transactional outbox flow backed by PostgreSQL
- workflow progression tracked in `workflow_state`
- terminal order outcomes reflected in `orders.status`
- containerized local startup with Docker Compose
- end-to-end tests for happy-path, inventory-failure, and payment-failure scenarios
- GitHub Actions CI for Compose startup and test execution
- lightweight structured logging for core workflow activity

## Known Limitations Of The Demo Design

The current implementation is intentionally simple and has several tradeoffs:

- all services share one PostgreSQL instance instead of owning separate databases
- all events are stored in one shared `outbox_events` table
- asynchronous progression is driven by dispatcher polling rather than a real message broker
- retry behavior is limited; there is no dead-letter queue or backoff strategy
- payment authorization uses a demo rule based only on order amount
- there is no authentication, authorization, or tenant isolation
- observability is limited to logs, health endpoints, and basic test coverage
- event schema versioning and backward-compatibility handling are not implemented

## Near-Term Next Improvements

Reasonable next steps for the current codebase include:

- add explicit retry policies and dead-letter handling for failed event processing
- expose simple metrics for processed events, failures, and dispatcher activity
- add request correlation IDs so cross-service log tracing is easier
- expand test coverage around invalid event payloads and operational edge cases
- add a small operational dashboard or status endpoint for workflow counts and failures

## Production-Grade Future Enhancements

For a more production-oriented design, the strongest upgrades would be:

- move to separate databases per service with clearer ownership boundaries
- replace the polling dispatcher with Kafka or RabbitMQ for event delivery
- add resilient consumer patterns such as retries, backoff, poison-message handling, and dead-letter queues
- introduce distributed tracing and richer observability with metrics, dashboards, and alerts
- add authentication and authorization for service APIs
- formalize event contracts with schema evolution and compatibility checks
- add deployment-grade concerns such as secrets management, rate limiting, and environment-specific configuration
