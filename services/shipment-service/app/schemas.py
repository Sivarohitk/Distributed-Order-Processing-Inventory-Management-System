from pydantic import BaseModel


class ShipmentResponse(BaseModel):
    shipment_id: str
    order_id: str
    status: str


class ProcessedShipmentEventResult(BaseModel):
    event_id: str
    order_id: str
    result: str


class ProcessShipmentEventsResponse(BaseModel):
    processed_count: int
    results: list[ProcessedShipmentEventResult]