
from sqlalchemy import Float, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from sqlalchemy.orm import Mapped, mapped_column, relationship


# Map the existing SQLite products table to a Python class.
class Product(Base):
    __tablename__ = "dim_products"

    # Identify each product using its existing business key.
    item_code: Mapped[str] = mapped_column(
        Text,
        primary_key=True,
    )

    # Describe the product and its catalog classification.
    item_description: Mapped[str] = mapped_column(Text, nullable=False)
    brand: Mapped[str] = mapped_column(Text, nullable=False)
    family: Mapped[str] = mapped_column(Text, nullable=False)
    sku_type: Mapped[str] = mapped_column(Text, nullable=False)

    # Store nominal product size and physical properties.
    unit_volume_ml_gm: Mapped[float] = mapped_column(Float, nullable=False)
    packaging_type: Mapped[str] = mapped_column(Text, nullable=False)
    product_viscosity: Mapped[str] = mapped_column(Text, nullable=False)
    density_sg: Mapped[float] = mapped_column(Float, nullable=False)

    # Product size unit is required for every product.
    size_unit: Mapped[str] = mapped_column(Text, nullable=False,)

    # Access the raw material BOM lines for this product.
    bom_items: Mapped[list["ProductBOMItem"]] = relationship(
    "ProductBOMItem",
    back_populates="product",)

    # Access packaging components required by this product.
    packaging_items: Mapped[list["ProductPackagingItem"]] = relationship(
    "ProductPackagingItem",
    back_populates="product",)
