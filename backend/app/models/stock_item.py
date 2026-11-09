
from sqlalchemy import ForeignKey, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base


# Represent an item that can be stored in inventory.
class StockItem(Base):
    __tablename__ = "stock_items"

    # Unique inventory identifier.
    stock_item_id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
    )

    item_name: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    item_type: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    # A material stock item references the materials catalog.
    material_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("materials.material_id"),
        nullable=True,
    )

    # A packaging stock item references the packaging catalog.
    packaging_sku: Mapped[str | None] = mapped_column(
        Text,
        ForeignKey("packaging_items.packaging_sku"),
        nullable=True,
    )

    # A finished product references the products catalog.
    product_item_code: Mapped[str | None] = mapped_column(
        Text,
        ForeignKey("dim_products.item_code"),
        nullable=True,
    )

    # Materials use grams; packaging and products use pieces.
    base_unit: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    # Access inventory movements associated with this stock item.
    movements: Mapped[list["InventoryMovement"]] = relationship(
    "InventoryMovement",
    back_populates="stock_item",
    )
