from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class OperationType(str, enum.Enum):
    RECEIPT = "receipt"
    TRANSFER_SHIP = "transfer_ship"
    TRANSFER_RECEIVE = "transfer_receive"
    FBS_RESERVE = "fbs_reserve"
    FBS_CANCEL = "fbs_cancel"
    FBS_SHIP = "fbs_ship"
    FBO_SHIP = "fbo_ship"
    FBO_RECEIVE = "fbo_receive"
    WAREHOUSE_DELETE = "warehouse_delete"


class TransitType(str, enum.Enum):
    FF_TRANSFER = "ff_transfer"
    FBO = "fbo"
    FBS_TO_CUSTOMER = "fbs_to_customer"


class TransitStatus(str, enum.Enum):
    IN_TRANSIT = "in_transit"
    COMPLETED = "completed"


class Shop(Base):
    __tablename__ = "shops"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)

    warehouses: Mapped[list[Warehouse]] = relationship(back_populates="shop")


class Warehouse(Base):
    __tablename__ = "warehouses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    shop_id: Mapped[int] = mapped_column(ForeignKey("shops.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    shop: Mapped[Shop] = relationship(back_populates="warehouses")
    balances: Mapped[list[StockBalance]] = relationship(back_populates="warehouse")


class Product(Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sku: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)

    balances: Mapped[list[StockBalance]] = relationship(back_populates="product")


class StockBalance(Base):
    __tablename__ = "stock_balances"
    __table_args__ = (UniqueConstraint("warehouse_id", "product_id", name="uq_balance_wh_product"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    warehouse_id: Mapped[int] = mapped_column(ForeignKey("warehouses.id"), nullable=False)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False)
    on_hand: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    reserved_fbs: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    warehouse: Mapped[Warehouse] = relationship(back_populates="balances")
    product: Mapped[Product] = relationship(back_populates="balances")

    @property
    def available(self) -> int:
        return self.on_hand - self.reserved_fbs


class Operation(Base):
    __tablename__ = "operations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    type: Mapped[OperationType] = mapped_column(Enum(OperationType, name="operation_type"), nullable=False)
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id"), nullable=True)
    quantity: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    from_warehouse_id: Mapped[int | None] = mapped_column(ForeignKey("warehouses.id"), nullable=True)
    to_warehouse_id: Mapped[int | None] = mapped_column(ForeignKey("warehouses.id"), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    product: Mapped[Product | None] = relationship()
    from_warehouse: Mapped[Warehouse | None] = relationship(foreign_keys=[from_warehouse_id])
    to_warehouse: Mapped[Warehouse | None] = relationship(foreign_keys=[to_warehouse_id])
    transit: Mapped[TransitShipment | None] = relationship(
        back_populates="operation",
        uselist=False,
        foreign_keys="TransitShipment.operation_id",
    )


class TransitShipment(Base):
    __tablename__ = "transit_shipments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    operation_id: Mapped[int] = mapped_column(ForeignKey("operations.id"), unique=True, nullable=False)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    transit_type: Mapped[TransitType] = mapped_column(Enum(TransitType, name="transit_type"), nullable=False)
    status: Mapped[TransitStatus] = mapped_column(
        Enum(TransitStatus, name="transit_status"),
        default=TransitStatus.IN_TRANSIT,
        nullable=False,
    )
    from_warehouse_id: Mapped[int | None] = mapped_column(ForeignKey("warehouses.id"), nullable=True)
    to_warehouse_id: Mapped[int | None] = mapped_column(ForeignKey("warehouses.id"), nullable=True)
    completed_operation_id: Mapped[int | None] = mapped_column(ForeignKey("operations.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    operation: Mapped[Operation] = relationship(
        back_populates="transit",
        foreign_keys=[operation_id],
    )
    product: Mapped[Product] = relationship()
    from_warehouse: Mapped[Warehouse | None] = relationship(foreign_keys=[from_warehouse_id])
    to_warehouse: Mapped[Warehouse | None] = relationship(foreign_keys=[to_warehouse_id])