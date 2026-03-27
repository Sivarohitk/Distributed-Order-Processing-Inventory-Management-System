from pydantic import BaseModel


class PaymentResponse(BaseModel):
    payment_id: str
    order_id: str
    amount: float
    currency: str
    status: str


class ProcessedPaymentEventResult(BaseModel):
    event_id: str
    order_id: str
    result: str


class ProcessPaymentEventsResponse(BaseModel):
    processed_count: int
    results: list[ProcessedPaymentEventResult]