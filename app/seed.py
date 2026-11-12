from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Operation, OperationType, Product, Shop, StockBalance, Warehouse


SEED_BALANCES = [
    ("SKU-101", "Органайзер", "Север", 10),
    ("SKU-101", "Органайзер", "Юг", 6),
    ("SKU-102", "Контейнер", "Север", 5),
    ("SKU-102", "Контейнер", "Юг", 0),
    ("SKU-103", "Корзина", "Север", 0),
    ("SKU-103", "Корзина", "Юг", 4),
]


def seed_if_empty(db: Session) -> None:
    product_count = db.scalar(select(func.count()).select_from(Product)) or 0
    if product_count > 0:
        return

    shop = Shop(name="Демо-магазин")
    db.add(shop)
    db.flush()

    north = Warehouse(shop_id=shop.id, name="Север", is_active=True)
    south = Warehouse(shop_id=shop.id, name="Юг", is_active=True)
    db.add_all([north, south])
    db.flush()

    warehouses = {"Север": north, "Юг": south}
    products: dict[str, Product] = {}

    for sku, name, wh_name, qty in SEED_BALANCES:
        if sku not in products:
            product = Product(sku=sku, name=name)
            db.add(product)
            db.flush()
            products[sku] = product
        product = products[sku]
        warehouse = warehouses[wh_name]
        db.add(
            StockBalance(
                warehouse_id=warehouse.id,
                product_id=product.id,
                on_hand=qty,
                reserved_fbs=0,
            )
        )
        if qty > 0:
            db.add(
                Operation(
                    idempotency_key=f"seed-receipt-{sku}-{wh_name}",
                    type=OperationType.RECEIPT,
                    product_id=product.id,
                    quantity=qty,
                    to_warehouse_id=warehouse.id,
                    note="Тестовый приход (seed)",
                )
            )

    db.commit()