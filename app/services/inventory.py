from __future__ import annotations

from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.models import (
    Operation,
    OperationType,
    Product,
    StockBalance,
    TransitShipment,
    TransitStatus,
    TransitType,
    Warehouse,
)
from app.schemas import (
    BalanceCell,
    OperationOut,
    ProductStockRow,
    StockOverview,
    TransitOut,
    WarehouseOut,
)


class ShortageException(HTTPException):
    def __init__(
        self,
        *,
        product_id: int,
        warehouse_id: int,
        requested: int,
        available_on_warehouse: int,
        available_total: int,
        alternatives: list[BalanceCell],
    ) -> None:
        detail = {
            "detail": (
                f"Нехватка на выбранном ФФ: нужно {requested}, доступно {available_on_warehouse}. "
                f"Общий доступный остаток по всем ФФ: {available_total}."
            ),
            "code": "shortage_on_warehouse",
            "product_id": product_id,
            "warehouse_id": warehouse_id,
            "requested": requested,
            "available_on_warehouse": available_on_warehouse,
            "available_total": available_total,
            "alternatives": [a.model_dump() for a in alternatives],
        }
        super().__init__(status_code=status.HTTP_409_CONFLICT, detail=detail)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def get_or_create_balance(db: Session, warehouse_id: int, product_id: int) -> StockBalance:
    balance = db.scalar(
        select(StockBalance).where(
            StockBalance.warehouse_id == warehouse_id,
            StockBalance.product_id == product_id,
        )
    )
    if balance is None:
        balance = StockBalance(
            warehouse_id=warehouse_id,
            product_id=product_id,
            on_hand=0,
            reserved_fbs=0,
        )
        db.add(balance)
        db.flush()
    return balance


def _active_warehouse(db: Session, warehouse_id: int) -> Warehouse:
    warehouse = db.get(Warehouse, warehouse_id)
    if warehouse is None:
        raise HTTPException(status_code=404, detail="Склад не найден")
    if not warehouse.is_active:
        raise HTTPException(status_code=400, detail="Склад удалён, операции недоступны")
    return warehouse


def _product(db: Session, product_id: int) -> Product:
    product = db.get(Product, product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="Товар не найден")
    return product


def _find_existing(db: Session, idempotency_key: str) -> Operation | None:
    return db.scalar(select(Operation).where(Operation.idempotency_key == idempotency_key))


def _operation_out(op: Operation, reused: bool = False) -> OperationOut:
    return OperationOut(
        id=op.id,
        idempotency_key=op.idempotency_key,
        type=op.type.value,
        product_id=op.product_id,
        sku=op.product.sku if op.product else None,
        product_name=op.product.name if op.product else None,
        quantity=op.quantity,
        from_warehouse_id=op.from_warehouse_id,
        from_warehouse_name=op.from_warehouse.name if op.from_warehouse else None,
        to_warehouse_id=op.to_warehouse_id,
        to_warehouse_name=op.to_warehouse.name if op.to_warehouse else None,
        note=op.note,
        created_at=op.created_at,
        reused=reused,
    )


def _ensure_available(db: Session, warehouse_id: int, product_id: int, qty: int) -> StockBalance:
    balance = get_or_create_balance(db, warehouse_id, product_id)
    if balance.available >= qty:
        return balance

    all_balances = db.scalars(
        select(StockBalance)
        .options(joinedload(StockBalance.warehouse))
        .where(StockBalance.product_id == product_id)
    ).all()
    alternatives = [
        BalanceCell(
            warehouse_id=b.warehouse_id,
            warehouse_name=b.warehouse.name,
            warehouse_active=b.warehouse.is_active,
            on_hand=b.on_hand,
            reserved_fbs=b.reserved_fbs,
            available=b.available,
        )
        for b in all_balances
        if b.warehouse.is_active and b.available > 0 and b.warehouse_id != warehouse_id
    ]
    available_total = sum(b.available for b in all_balances if b.warehouse.is_active)
    raise ShortageException(
        product_id=product_id,
        warehouse_id=warehouse_id,
        requested=qty,
        available_on_warehouse=balance.available,
        available_total=available_total,
        alternatives=alternatives,
    )


def create_receipt(
    db: Session,
    *,
    idempotency_key: str,
    product_id: int,
    warehouse_id: int,
    quantity: int,
    note: str | None,
) -> OperationOut:
    existing = _find_existing(db, idempotency_key)
    if existing:
        return _operation_out(existing, reused=True)

    _product(db, product_id)
    _active_warehouse(db, warehouse_id)
    balance = get_or_create_balance(db, warehouse_id, product_id)
    balance.on_hand += quantity

    op = Operation(
        idempotency_key=idempotency_key,
        type=OperationType.RECEIPT,
        product_id=product_id,
        quantity=quantity,
        to_warehouse_id=warehouse_id,
        note=note or "Приход на ФФ",
    )
    db.add(op)
    db.commit()
    db.refresh(op)
    return _operation_out(op)


def transfer_ship(
    db: Session,
    *,
    idempotency_key: str,
    product_id: int,
    from_warehouse_id: int,
    to_warehouse_id: int,
    quantity: int,
    note: str | None,
) -> OperationOut:
    existing = _find_existing(db, idempotency_key)
    if existing:
        return _operation_out(existing, reused=True)

    if from_warehouse_id == to_warehouse_id:
        raise HTTPException(status_code=400, detail="Склады отправителя и получателя должны отличаться")

    _product(db, product_id)
    _active_warehouse(db, from_warehouse_id)
    _active_warehouse(db, to_warehouse_id)
    balance = _ensure_available(db, from_warehouse_id, product_id, quantity)
    balance.on_hand -= quantity

    op = Operation(
        idempotency_key=idempotency_key,
        type=OperationType.TRANSFER_SHIP,
        product_id=product_id,
        quantity=quantity,
        from_warehouse_id=from_warehouse_id,
        to_warehouse_id=to_warehouse_id,
        note=note or "Отправка перемещения между ФФ",
    )
    db.add(op)
    db.flush()
    db.add(
        TransitShipment(
            operation_id=op.id,
            product_id=product_id,
            quantity=quantity,
            transit_type=TransitType.FF_TRANSFER,
            status=TransitStatus.IN_TRANSIT,
            from_warehouse_id=from_warehouse_id,
            to_warehouse_id=to_warehouse_id,
        )
    )
    db.commit()
    db.refresh(op)
    return _operation_out(op)


def transfer_receive(
    db: Session,
    *,
    idempotency_key: str,
    transit_id: int,
    note: str | None,
) -> OperationOut:
    existing = _find_existing(db, idempotency_key)
    if existing:
        return _operation_out(existing, reused=True)

    transit = db.get(TransitShipment, transit_id)
    if transit is None:
        raise HTTPException(status_code=404, detail="Перемещение не найдено")
    if transit.transit_type != TransitType.FF_TRANSFER:
        raise HTTPException(status_code=400, detail="Это не перемещение между ФФ")
    if transit.status != TransitStatus.IN_TRANSIT:
        raise HTTPException(status_code=400, detail="Перемещение уже принято")
    if transit.to_warehouse_id is None:
        raise HTTPException(status_code=400, detail="Не указан склад назначения")

    _active_warehouse(db, transit.to_warehouse_id)
    balance = get_or_create_balance(db, transit.to_warehouse_id, transit.product_id)
    balance.on_hand += transit.quantity

    op = Operation(
        idempotency_key=idempotency_key,
        type=OperationType.TRANSFER_RECEIVE,
        product_id=transit.product_id,
        quantity=transit.quantity,
        from_warehouse_id=transit.from_warehouse_id,
        to_warehouse_id=transit.to_warehouse_id,
        note=note or "Приёмка перемещения между ФФ",
    )
    db.add(op)
    db.flush()
    transit.status = TransitStatus.COMPLETED
    transit.completed_at = _now()
    transit.completed_operation_id = op.id
    db.commit()
    db.refresh(op)
    return _operation_out(op)


def fbs_reserve(
    db: Session,
    *,
    idempotency_key: str,
    product_id: int,
    warehouse_id: int,
    quantity: int,
    note: str | None,
) -> OperationOut:
    existing = _find_existing(db, idempotency_key)
    if existing:
        return _operation_out(existing, reused=True)

    _product(db, product_id)
    _active_warehouse(db, warehouse_id)
    balance = _ensure_available(db, warehouse_id, product_id, quantity)
    balance.reserved_fbs += quantity

    op = Operation(
        idempotency_key=idempotency_key,
        type=OperationType.FBS_RESERVE,
        product_id=product_id,
        quantity=quantity,
        from_warehouse_id=warehouse_id,
        note=note or "Резерв FBS",
    )
    db.add(op)
    db.commit()
    db.refresh(op)
    return _operation_out(op)


def fbs_cancel(
    db: Session,
    *,
    idempotency_key: str,
    product_id: int,
    warehouse_id: int,
    quantity: int,
    note: str | None,
) -> OperationOut:
    existing = _find_existing(db, idempotency_key)
    if existing:
        return _operation_out(existing, reused=True)

    _product(db, product_id)
    _active_warehouse(db, warehouse_id)
    balance = get_or_create_balance(db, warehouse_id, product_id)
    if balance.reserved_fbs < quantity:
        raise HTTPException(
            status_code=409,
            detail=f"Недостаточно резерва FBS: есть {balance.reserved_fbs}, нужно {quantity}",
        )
    balance.reserved_fbs -= quantity

    op = Operation(
        idempotency_key=idempotency_key,
        type=OperationType.FBS_CANCEL,
        product_id=product_id,
        quantity=quantity,
        to_warehouse_id=warehouse_id,
        note=note or "Отмена резерва FBS",
    )
    db.add(op)
    db.commit()
    db.refresh(op)
    return _operation_out(op)


def fbs_ship(
    db: Session,
    *,
    idempotency_key: str,
    product_id: int,
    warehouse_id: int,
    quantity: int,
    note: str | None,
) -> OperationOut:
    existing = _find_existing(db, idempotency_key)
    if existing:
        return _operation_out(existing, reused=True)

    _product(db, product_id)
    _active_warehouse(db, warehouse_id)
    balance = get_or_create_balance(db, warehouse_id, product_id)
    if balance.reserved_fbs < quantity:
        raise HTTPException(
            status_code=409,
            detail=f"Недостаточно резерва FBS для отправки: есть {balance.reserved_fbs}, нужно {quantity}",
        )
    balance.reserved_fbs -= quantity
    balance.on_hand -= quantity

    op = Operation(
        idempotency_key=idempotency_key,
        type=OperationType.FBS_SHIP,
        product_id=product_id,
        quantity=quantity,
        from_warehouse_id=warehouse_id,
        note=note or "Отправка FBS к клиенту",
    )
    db.add(op)
    db.flush()
    db.add(
        TransitShipment(
            operation_id=op.id,
            product_id=product_id,
            quantity=quantity,
            transit_type=TransitType.FBS_TO_CUSTOMER,
            status=TransitStatus.IN_TRANSIT,
            from_warehouse_id=warehouse_id,
            to_warehouse_id=None,
        )
    )
    db.commit()
    db.refresh(op)
    return _operation_out(op)


def fbo_ship(
    db: Session,
    *,
    idempotency_key: str,
    product_id: int,
    warehouse_id: int,
    quantity: int,
    note: str | None,
) -> OperationOut:
    existing = _find_existing(db, idempotency_key)
    if existing:
        return _operation_out(existing, reused=True)

    _product(db, product_id)
    _active_warehouse(db, warehouse_id)
    balance = _ensure_available(db, warehouse_id, product_id, quantity)
    balance.on_hand -= quantity

    op = Operation(
        idempotency_key=idempotency_key,
        type=OperationType.FBO_SHIP,
        product_id=product_id,
        quantity=quantity,
        from_warehouse_id=warehouse_id,
        note=note or "Отправка FBO на склад маркетплейса",
    )
    db.add(op)
    db.flush()
    db.add(
        TransitShipment(
            operation_id=op.id,
            product_id=product_id,
            quantity=quantity,
            transit_type=TransitType.FBO,
            status=TransitStatus.IN_TRANSIT,
            from_warehouse_id=warehouse_id,
            to_warehouse_id=None,
        )
    )
    db.commit()
    db.refresh(op)
    return _operation_out(op)


def fbo_receive(
    db: Session,
    *,
    idempotency_key: str,
    transit_id: int,
    note: str | None,
) -> OperationOut:
    existing = _find_existing(db, idempotency_key)
    if existing:
        return _operation_out(existing, reused=True)

    transit = db.get(TransitShipment, transit_id)
    if transit is None:
        raise HTTPException(status_code=404, detail="Отправка FBO не найдена")
    if transit.transit_type != TransitType.FBO:
        raise HTTPException(status_code=400, detail="Это не FBO-отправка")
    if transit.status != TransitStatus.IN_TRANSIT:
        raise HTTPException(status_code=400, detail="FBO уже принято на складе маркетплейса")

    op = Operation(
        idempotency_key=idempotency_key,
        type=OperationType.FBO_RECEIVE,
        product_id=transit.product_id,
        quantity=transit.quantity,
        from_warehouse_id=transit.from_warehouse_id,
        note=note or "Приёмка FBO на складе маркетплейса",
    )
    db.add(op)
    db.flush()
    transit.status = TransitStatus.COMPLETED
    transit.completed_at = _now()
    transit.completed_operation_id = op.id
    db.commit()
    db.refresh(op)
    return _operation_out(op)


def create_warehouse(db: Session, *, shop_id: int, name: str) -> Warehouse:
    name = name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Название склада обязательно")
    exists = db.scalar(
        select(Warehouse).where(
            Warehouse.shop_id == shop_id,
            Warehouse.name == name,
            Warehouse.is_active.is_(True),
        )
    )
    if exists:
        raise HTTPException(status_code=409, detail="Активный склад с таким именем уже есть")
    warehouse = Warehouse(shop_id=shop_id, name=name, is_active=True)
    db.add(warehouse)
    db.commit()
    db.refresh(warehouse)
    return warehouse


def rename_warehouse(db: Session, warehouse_id: int, name: str) -> Warehouse:
    warehouse = _active_warehouse(db, warehouse_id)
    name = name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Название склада обязательно")
    warehouse.name = name
    db.commit()
    db.refresh(warehouse)
    return warehouse


def delete_warehouse(db: Session, warehouse_id: int, idempotency_key: str) -> tuple[Warehouse, OperationOut]:
    existing = _find_existing(db, idempotency_key)
    if existing and existing.type == OperationType.WAREHOUSE_DELETE:
        warehouse = db.get(Warehouse, existing.from_warehouse_id)
        assert warehouse is not None
        return warehouse, _operation_out(existing, reused=True)

    warehouse = _active_warehouse(db, warehouse_id)
    balances = db.scalars(
        select(StockBalance).where(StockBalance.warehouse_id == warehouse_id)
    ).all()
    open_transit = db.scalars(
        select(TransitShipment).where(
            TransitShipment.status == TransitStatus.IN_TRANSIT,
            (
                (TransitShipment.from_warehouse_id == warehouse_id)
                | (TransitShipment.to_warehouse_id == warehouse_id)
            ),
        )
    ).all()
    if open_transit:
        raise HTTPException(
            status_code=409,
            detail="Нельзя удалить ФФ: есть незавершённые перемещения с участием склада",
        )

    total_units = sum(b.on_hand for b in balances)
    warehouse.is_active = False
    warehouse.deleted_at = _now()

    op = Operation(
        idempotency_key=idempotency_key,
        type=OperationType.WAREHOUSE_DELETE,
        product_id=None,
        quantity=total_units,
        from_warehouse_id=warehouse_id,
        note=(
            f"Удаление ФФ «{warehouse.name}». Остатки ({total_units} ед.) и история сохранены; "
            "товар по-прежнему числится на удалённом складе."
        ),
    )
    db.add(op)
    db.commit()
    db.refresh(warehouse)
    db.refresh(op)
    return warehouse, _operation_out(op)


def stock_overview(db: Session) -> StockOverview:
    products = db.scalars(select(Product).order_by(Product.sku)).all()
    warehouses = db.scalars(select(Warehouse).order_by(Warehouse.id)).all()
    balances = db.scalars(
        select(StockBalance).options(
            joinedload(StockBalance.warehouse),
            joinedload(StockBalance.product),
        )
    ).all()
    transit_rows = db.scalars(
        select(TransitShipment)
        .options(
            joinedload(TransitShipment.product),
            joinedload(TransitShipment.from_warehouse),
            joinedload(TransitShipment.to_warehouse),
        )
        .where(TransitShipment.status == TransitStatus.IN_TRANSIT)
        .order_by(TransitShipment.id.desc())
    ).all()

    balance_map: dict[tuple[int, int], StockBalance] = {
        (b.product_id, b.warehouse_id): b for b in balances
    }

    product_rows: list[ProductStockRow] = []
    for product in products:
        cells: list[BalanceCell] = []
        for wh in warehouses:
            bal = balance_map.get((product.id, wh.id))
            on_hand = bal.on_hand if bal else 0
            reserved = bal.reserved_fbs if bal else 0
            cells.append(
                BalanceCell(
                    warehouse_id=wh.id,
                    warehouse_name=wh.name,
                    warehouse_active=wh.is_active,
                    on_hand=on_hand,
                    reserved_fbs=reserved,
                    available=on_hand - reserved,
                )
            )
        in_ff = sum(
            t.quantity
            for t in transit_rows
            if t.product_id == product.id and t.transit_type == TransitType.FF_TRANSFER
        )
        in_fbo = sum(
            t.quantity
            for t in transit_rows
            if t.product_id == product.id and t.transit_type == TransitType.FBO
        )
        in_fbs = sum(
            t.quantity
            for t in transit_rows
            if t.product_id == product.id and t.transit_type == TransitType.FBS_TO_CUSTOMER
        )
        product_rows.append(
            ProductStockRow(
                product_id=product.id,
                sku=product.sku,
                name=product.name,
                balances=cells,
                total_on_hand=sum(c.on_hand for c in cells),
                total_reserved_fbs=sum(c.reserved_fbs for c in cells),
                total_available=sum(c.available for c in cells),
                in_transit_ff=in_ff,
                in_transit_fbo=in_fbo,
                in_transit_fbs=in_fbs,
            )
        )

    transit_out = [
        TransitOut(
            id=t.id,
            product_id=t.product_id,
            sku=t.product.sku,
            product_name=t.product.name,
            quantity=t.quantity,
            transit_type=t.transit_type.value,
            status=t.status.value,
            from_warehouse_id=t.from_warehouse_id,
            from_warehouse_name=t.from_warehouse.name if t.from_warehouse else None,
            to_warehouse_id=t.to_warehouse_id,
            to_warehouse_name=t.to_warehouse.name if t.to_warehouse else None,
            created_at=t.created_at,
        )
        for t in transit_rows
    ]

    return StockOverview(
        products=product_rows,
        transit=transit_out,
        warehouses=[WarehouseOut.model_validate(w) for w in warehouses],
    )


def list_operations(db: Session, limit: int = 100) -> list[OperationOut]:
    ops = db.scalars(
        select(Operation)
        .options(
            joinedload(Operation.product),
            joinedload(Operation.from_warehouse),
            joinedload(Operation.to_warehouse),
        )
        .order_by(Operation.id.desc())
        .limit(limit)
    ).all()
    return [_operation_out(op) for op in ops]


def list_products(db: Session) -> list[Product]:
    return list(db.scalars(select(Product).order_by(Product.sku)).all())


def list_warehouses(db: Session, include_deleted: bool = True) -> list[Warehouse]:
    stmt = select(Warehouse).order_by(Warehouse.id)
    if not include_deleted:
        stmt = stmt.where(Warehouse.is_active.is_(True))
    return list(db.scalars(stmt).all())