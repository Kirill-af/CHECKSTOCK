from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas import (
    FboReceiveRequest,
    FboShipRequest,
    FbsCancelRequest,
    FbsReserveRequest,
    FbsShipRequest,
    MessageOut,
    OperationOut,
    ProductOut,
    ReceiptRequest,
    StockOverview,
    TransferReceiveRequest,
    TransferShipRequest,
    WarehouseCreate,
    WarehouseOut,
    WarehouseRename,
)
from app.services import inventory as svc

router = APIRouter(prefix="/api")


@router.get("/stock", response_model=StockOverview)
def get_stock(db: Session = Depends(get_db)) -> StockOverview:
    return svc.stock_overview(db)


@router.get("/products", response_model=list[ProductOut])
def get_products(db: Session = Depends(get_db)) -> list[ProductOut]:
    return [ProductOut.model_validate(p) for p in svc.list_products(db)]


@router.get("/warehouses", response_model=list[WarehouseOut])
def get_warehouses(
    include_deleted: bool = Query(True),
    db: Session = Depends(get_db),
) -> list[WarehouseOut]:
    return [WarehouseOut.model_validate(w) for w in svc.list_warehouses(db, include_deleted)]


@router.post("/warehouses", response_model=WarehouseOut)
def post_warehouse(payload: WarehouseCreate, db: Session = Depends(get_db)) -> WarehouseOut:
    return WarehouseOut.model_validate(
        svc.create_warehouse(db, shop_id=payload.shop_id, name=payload.name)
    )


@router.patch("/warehouses/{warehouse_id}", response_model=WarehouseOut)
def patch_warehouse(
    warehouse_id: int,
    payload: WarehouseRename,
    db: Session = Depends(get_db),
) -> WarehouseOut:
    return WarehouseOut.model_validate(svc.rename_warehouse(db, warehouse_id, payload.name))


@router.delete("/warehouses/{warehouse_id}", response_model=MessageOut)
def delete_warehouse(
    warehouse_id: int,
    idempotency_key: str = Query(..., min_length=8, max_length=120),
    db: Session = Depends(get_db),
) -> MessageOut:
    warehouse, operation = svc.delete_warehouse(db, warehouse_id, idempotency_key)
    return MessageOut(
        detail=(
            f"ФФ «{warehouse.name}» удалён. Остатки и история сохранены; "
            "товар продолжает числиться на удалённом складе."
        ),
        warehouse=WarehouseOut.model_validate(warehouse),
        operation=operation,
    )


@router.post("/operations/receipt", response_model=OperationOut)
def post_receipt(payload: ReceiptRequest, db: Session = Depends(get_db)) -> OperationOut:
    return svc.create_receipt(
        db,
        idempotency_key=payload.idempotency_key,
        product_id=payload.product_id,
        warehouse_id=payload.warehouse_id,
        quantity=payload.quantity,
        note=payload.note,
    )


@router.post("/operations/transfer/ship", response_model=OperationOut)
def post_transfer_ship(payload: TransferShipRequest, db: Session = Depends(get_db)) -> OperationOut:
    return svc.transfer_ship(
        db,
        idempotency_key=payload.idempotency_key,
        product_id=payload.product_id,
        from_warehouse_id=payload.from_warehouse_id,
        to_warehouse_id=payload.to_warehouse_id,
        quantity=payload.quantity,
        note=payload.note,
    )


@router.post("/operations/transfer/receive", response_model=OperationOut)
def post_transfer_receive(
    payload: TransferReceiveRequest,
    db: Session = Depends(get_db),
) -> OperationOut:
    return svc.transfer_receive(
        db,
        idempotency_key=payload.idempotency_key,
        transit_id=payload.transit_id,
        note=payload.note,
    )


@router.post("/operations/fbs/reserve", response_model=OperationOut)
def post_fbs_reserve(payload: FbsReserveRequest, db: Session = Depends(get_db)) -> OperationOut:
    return svc.fbs_reserve(
        db,
        idempotency_key=payload.idempotency_key,
        product_id=payload.product_id,
        warehouse_id=payload.warehouse_id,
        quantity=payload.quantity,
        note=payload.note,
    )


@router.post("/operations/fbs/cancel", response_model=OperationOut)
def post_fbs_cancel(payload: FbsCancelRequest, db: Session = Depends(get_db)) -> OperationOut:
    return svc.fbs_cancel(
        db,
        idempotency_key=payload.idempotency_key,
        product_id=payload.product_id,
        warehouse_id=payload.warehouse_id,
        quantity=payload.quantity,
        note=payload.note,
    )


@router.post("/operations/fbs/ship", response_model=OperationOut)
def post_fbs_ship(payload: FbsShipRequest, db: Session = Depends(get_db)) -> OperationOut:
    return svc.fbs_ship(
        db,
        idempotency_key=payload.idempotency_key,
        product_id=payload.product_id,
        warehouse_id=payload.warehouse_id,
        quantity=payload.quantity,
        note=payload.note,
    )


@router.post("/operations/fbo/ship", response_model=OperationOut)
def post_fbo_ship(payload: FboShipRequest, db: Session = Depends(get_db)) -> OperationOut:
    return svc.fbo_ship(
        db,
        idempotency_key=payload.idempotency_key,
        product_id=payload.product_id,
        warehouse_id=payload.warehouse_id,
        quantity=payload.quantity,
        note=payload.note,
    )


@router.post("/operations/fbo/receive", response_model=OperationOut)
def post_fbo_receive(payload: FboReceiveRequest, db: Session = Depends(get_db)) -> OperationOut:
    return svc.fbo_receive(
        db,
        idempotency_key=payload.idempotency_key,
        transit_id=payload.transit_id,
        note=payload.note,
    )


@router.get("/operations", response_model=list[OperationOut])
def get_operations(
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
) -> list[OperationOut]:
    return svc.list_operations(db, limit=limit)