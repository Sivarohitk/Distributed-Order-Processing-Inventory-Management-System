from pydantic import BaseModel, Field
from typing import Literal


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
    status: Literal["PENDING"]
    message: str