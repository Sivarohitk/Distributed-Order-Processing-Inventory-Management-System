# Workflow Diagrams

See also:
- [Repository README](../README.md)
- [Architecture Notes](architecture.md)

## High-Level Workflow Diagram

```mermaid
flowchart LR
    Client["Client"]
    Order["order-service"]
    Inventory["inventory-service"]
    Payment["payment-service"]
    Shipment["shipment-service"]
    Dispatcher["dispatcher-service"]
    DB["PostgreSQL shared database<br/>orders<br/>workflow_state<br/>outbox_events<br/>inventory_stock<br/>inventory_reservations<br/>payments<br/>shipments"]

    Client -->|"POST /orders"| Order
    Order -->|"insert order + workflow_state + order.created"| DB

    Dispatcher -.->|"POST /events/process"| Inventory
    DB -->|"pending order.created"| Inventory
    Inventory -->|"update stock/reservation + insert inventory.reserved (with amount/currency) or inventory.failed"| DB

    Dispatcher -.->|"POST /events/process"| Payment
    DB -->|"pending inventory.reserved"| Payment
    Payment -->|"insert payment + insert payment.authorized or payment.failed"| DB

    Dispatcher -.->|"POST /events/process"| Shipment
    DB -->|"pending payment.authorized"| Shipment
    Shipment -->|"insert shipment + insert shipment.created"| DB
```

Notes:

- `dispatcher-service` automates progression by calling the downstream processing endpoints on a loop.
- `inventory.failed`, `payment.failed`, and `shipment.created` are still emitted in the current implementation, but they are stored as already handled audit events instead of being left pending.

## Workflow State Progression Diagram

```mermaid
stateDiagram-v2
    [*] --> ORDER_CREATED

    state "ORDER_CREATED" as ORDER_CREATED
    note right of ORDER_CREATED
      current_step = ORDER_CREATED
      order_status = PENDING
      inventory_status = NOT_STARTED
      payment_status = NOT_STARTED
      shipment_status = NOT_STARTED
    end note

    state "INVENTORY_RESERVED" as INVENTORY_RESERVED
    note right of INVENTORY_RESERVED
      current_step = INVENTORY_RESERVED
      order_status = PENDING
      inventory_status = RESERVED
      payment_status = NOT_STARTED
      shipment_status = NOT_STARTED
    end note

    state "INVENTORY_REJECTED" as INVENTORY_REJECTED
    note right of INVENTORY_REJECTED
      current_step = INVENTORY_REJECTED
      order_status = FAILED
      inventory_status = FAILED
      payment_status = NOT_STARTED
      shipment_status = NOT_STARTED
    end note

    state "PAYMENT_AUTHORIZED" as PAYMENT_AUTHORIZED
    note right of PAYMENT_AUTHORIZED
      current_step = PAYMENT_AUTHORIZED
      order_status = PENDING
      inventory_status = RESERVED
      payment_status = AUTHORIZED
      shipment_status = NOT_STARTED
    end note

    state "PAYMENT_FAILED" as PAYMENT_FAILED
    note right of PAYMENT_FAILED
      current_step = PAYMENT_FAILED
      order_status = FAILED
      inventory_status = RESERVED
      payment_status = FAILED
      shipment_status = NOT_STARTED
    end note

    state "SHIPMENT_CREATED" as SHIPMENT_CREATED
    note right of SHIPMENT_CREATED
      current_step = SHIPMENT_CREATED
      order_status = COMPLETED
      inventory_status = RESERVED
      payment_status = AUTHORIZED
      shipment_status = CREATED
    end note

    ORDER_CREATED --> INVENTORY_RESERVED: inventory.reserved
    ORDER_CREATED --> INVENTORY_REJECTED: inventory.failed
    INVENTORY_RESERVED --> PAYMENT_AUTHORIZED: payment.authorized
    INVENTORY_RESERVED --> PAYMENT_FAILED: payment.failed
    PAYMENT_AUTHORIZED --> SHIPMENT_CREATED: shipment.created
    INVENTORY_REJECTED --> [*]
    PAYMENT_FAILED --> [*]
    SHIPMENT_CREATED --> [*]
```

This state diagram reflects the values stored in the `workflow_state` table today. The `orders.status` column now mirrors the terminal lifecycle outcome: it stays `PENDING` while work is in flight, then becomes `FAILED` or `COMPLETED` when the workflow reaches a terminal state.
