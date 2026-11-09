
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import InventoryMovement, StockItem, Warehouse


# Calculate the recorded balance of one item in one warehouse.
def get_stock_balance(
    db: Session,
    stock_item_id: int,
    warehouse_id: int,
) -> float:
    statement = (
        select(
            func.coalesce(
                func.sum(InventoryMovement.quantity_delta),
                0,
            )
        )
        .where(
            InventoryMovement.stock_item_id == stock_item_id,
            InventoryMovement.warehouse_id == warehouse_id,
        )
    )

    return float(db.scalar(statement))


# Retrieve the recorded balance of every stock item.
def get_all_stock_balances(db: Session) -> list[dict]:
    statement = (
        select(
            StockItem.stock_item_id,
            StockItem.item_name,
            StockItem.item_type,
            StockItem.base_unit,
            Warehouse.warehouse_id,
            Warehouse.warehouse_name,
            func.coalesce(
                func.sum(InventoryMovement.quantity_delta),
                0,
            ).label("current_balance"),
        )
        .join(
            Warehouse,
            (
                (StockItem.item_type == "FINISHED_PRODUCT")
                & (Warehouse.warehouse_type == "FINISHED_GOODS")
            )
            |
            (
                (StockItem.item_type != "FINISHED_PRODUCT")
                & (Warehouse.warehouse_type == "RAW_MATERIALS")
            ),
        )
        .outerjoin(
            InventoryMovement,
            (
                (InventoryMovement.stock_item_id == StockItem.stock_item_id)
                & (InventoryMovement.warehouse_id == Warehouse.warehouse_id)
            ),
        )
        .group_by(
            StockItem.stock_item_id,
            StockItem.item_name,
            StockItem.item_type,
            StockItem.base_unit,
            Warehouse.warehouse_id,
            Warehouse.warehouse_name,
        )
        .order_by(StockItem.stock_item_id)
    )

    rows = db.execute(statement).all()

    return [
        {
            "stock_item_id": row.stock_item_id,
            "item_name": row.item_name,
            "item_type": row.item_type,
            "base_unit": row.base_unit,
            "warehouse_id": row.warehouse_id,
            "warehouse_name": row.warehouse_name,
            "current_balance": float(row.current_balance),
        }
        for row in rows
    ]


# Find the inventory item linked to a raw material.
def get_stock_item_by_material(
    db: Session,
    material_id: int,
) -> StockItem | None:
    statement = select(StockItem).where(
        StockItem.material_id == material_id,
        StockItem.item_type == "MATERIAL",
    )

    return db.scalar(statement)


# Find the inventory item linked to a packaging component.
def get_stock_item_by_packaging(
    db: Session,
    packaging_sku: str,
) -> StockItem | None:
    statement = select(StockItem).where(
        StockItem.packaging_sku == packaging_sku,
        StockItem.item_type == "PACKAGING",
    )

    return db.scalar(statement)
