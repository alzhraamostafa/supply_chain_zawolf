
from sqlalchemy import ForeignKey, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


# Map the existing packaging catalog table.
class PackagingItem(Base):
    __tablename__ = "packaging_items"

    packaging_sku: Mapped[str] = mapped_column(
        Text,
        primary_key=True,
    )

    packaging_type: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    base_unit: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    # Access product-to-packaging associations.
    product_items: Mapped[list["ProductPackagingItem"]] = relationship(
        "ProductPackagingItem",
        back_populates="packaging",
    )


# Map the packaging requirements of each finished product.
class ProductPackagingItem(Base):
    __tablename__ = "product_packaging_items"

    # Both fields form the existing composite primary key.
    item_code: Mapped[str] = mapped_column(
        Text,
        ForeignKey("dim_products.item_code"),
        primary_key=True,
    )

    packaging_sku: Mapped[str] = mapped_column(
        Text,
        ForeignKey("packaging_items.packaging_sku"),
        primary_key=True,
    )

    # Number of packaging components required per finished product.
    quantity_per_piece: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    # Navigate from the association to its packaging catalog item.
    packaging: Mapped["PackagingItem"] = relationship(
        "PackagingItem",
        back_populates="product_items",
    )

    # Navigate from the association to its finished product.
    product: Mapped["Product"] = relationship(
        "Product",
        back_populates="packaging_items",
    )
