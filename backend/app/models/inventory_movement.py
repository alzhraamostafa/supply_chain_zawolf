
from sqlalchemy import Float, ForeignKey, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


# Map an existing inventory ledger transaction.
class InventoryMovement(Base):
    __tablename__ = "inventory_movements"

    movement_id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
    )

    # Reference the affected stock item and warehouse.
    stock_item_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("stock_items.stock_item_id"),
        nullable=False,
    )

    warehouse_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("warehouses.warehouse_id"),
        nullable=False,
    )

    # Store the movement category and signed quantity.
    movement_type: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    quantity_delta: Mapped[float] = mapped_column(
        Float,
        nullable=False,
    )

    # Reference the source business document when available.
    source_document_type: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    source_document_id: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    movement_date: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    # Navigate from a ledger movement to its stock item.
    stock_item: Mapped["StockItem"] = relationship(
        "StockItem",
        back_populates="movements",
    )

    # Navigate from a ledger movement to its warehouse.
    warehouse: Mapped["Warehouse"] = relationship(
        "Warehouse",
        back_populates="movements",
    )
