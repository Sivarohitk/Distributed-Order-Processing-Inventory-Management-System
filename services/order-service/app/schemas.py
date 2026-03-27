from datetime import datetime
from typing import Any
from pydantic import BaseModel, Field


class OrderCreate(BaseModel):
    customer_id: str = Field(..., min_length=1)
    sku: str = Field(..., min_length=1)
    quantity: int = Field(..., gt=0)
    amount: float = Field(..., gt=0)
    currency: str = Field(..., min_length=3, max_length=3)


class OrderResponse(BaseModel):
    order_id: str
    customer_id: str
    sku: str
    quantity: int
    amount: float
    currency: str
    status: str
    message: str


class WorkflowStateResponse(BaseModel):
    order_id: str
    current_step: str
    order_status: str
    inventory_status: str
    payment_status: str
    shipment_status: str


class OutboxEventResponse(BaseModel):
    event_id: str
    aggregate_id: str
    event_type: str
    payload: dict[str, Any]
    status: str
    created_at: datetime