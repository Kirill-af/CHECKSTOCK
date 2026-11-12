from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class WarehouseCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    shop_id: int = 1


class WarehouseRename(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class WarehouseOut(BaseModel):
    id: int
    shop_id: int
    name: str
    is_active: bool
    deleted_at: datetime | None

    model_config = {"from_attributes": True}


class ProductOut(BaseModel):
    id: int
    sku: str
    name: str

    model_config = {"from_attributes": True}


class BalanceCell(BaseModel):
    warehouse_id: int
    warehouse_name: str
    warehouse_active: bool
    on_hand: int
    reserved_fbs: int
    available: int


class ProductStockRow(BaseModel):
    product_id: int
    sku: str
    name: str
    balances: list[BalanceCell]
    total_on_hand: int
    total_reserved_fbs: int
    total_available: int
    in_transit_ff: int
    in_transit_fbo: int
    in_transit_fbs: int


class TransitOut(BaseModel):
    id: int
    product_id: int
    sku: str
    product_name: str
    quantity: int
    transit_type: str
    status: str
    from_warehouse_id: int | None
    from_warehouse_name: str | None
    to_warehouse_id: int | None
    to_warehouse_name: str | None
    created_at: datetime


class StockOverview(BaseModel):
    products: list[ProductStockRow]
    transit: list[TransitOut]
    warehouses: list[WarehouseOut]


class IdempotentRequest(BaseModel):
    idempotency_key: str = Field(min_length=8, max_length=120)
    product_id: int
    quantity: int = Field(gt=0)


class ReceiptRequest(IdempotentRequest):
    warehouse_id: int
    note: str | None = None


class TransferShipRequest(IdempotentRequest):
    from_warehouse_id: int
    to_warehouse_id: int
    note: str | None = None


class TransferReceiveRequest(BaseModel):
    idempotency_key: str = Field(min_length=8, max_length=120)
    transit_id: int
    note: str | None = None


class FbsReserveRequest(IdempotentRequest):
    warehouse_id: int
    note: str | None = None


class FbsCancelRequest(IdempotentRequest):
    warehouse_id: int
    note: str | None = None


class FbsShipRequest(IdempotentRequest):
    warehouse_id: int
    note: str | None = None


class FboShipRequest(IdempotentRequest):
    warehouse_id: int
    note: str | None = None


class FboReceiveRequest(BaseModel):
    idempotency_key: str = Field(min_length=8, max_length=120)
    transit_id: int
    note: str | None = None


class OperationOut(BaseModel):
    id: int
    idempotency_key: str
    type: str
    product_id: int | None
    sku: str | None
    product_name: str | None
    quantity: int
    from_warehouse_id: int | None
    from_warehouse_name: str | None
    to_warehouse_id: int | None
    to_warehouse_name: str | None
    note: str | None
    created_at: datetime
    reused: bool = False


class ShortageError(BaseModel):
    detail: str
    code: Literal["shortage_on_warehouse"] = "shortage_on_warehouse"
    product_id: int
    warehouse_id: int
    requested: int
    available_on_warehouse: int
    available_total: int
    alternatives: list[BalanceCell]


class MessageOut(BaseModel):
    detail: str
    warehouse: WarehouseOut | None = None
    operation: OperationOut | None = None