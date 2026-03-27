from pydantic import BaseModel


class InventoryStockResponse(BaseModel):
    sku: str
    available_quantity: int


class InventoryReservationResponse(BaseModel):
    reservation_id: str
    order_id: str
    sku: str
    quantity: int
    status: str


class ProcessedEventResult(BaseModel):
    event_id: str
    order_id: str
    sku: str
    quantity: int
    result: str


class ProcessEventsResponse(BaseModel):
    processed_count: int
    results: list[ProcessedEventResult]