
from sqlalchemy import Float, ForeignKey, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


# Map each product-to-material BOM association.
class ProductBOMItem(Base):
    __tablename__ = "product_bom_items"

    # Both columns form the composite primary key.
    item_code: Mapped[str] = mapped_column(
        Text,
        ForeignKey("dim_products.item_code"),
        primary_key=True,
    )

    material_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("materials.material_id"),
        primary_key=True,
    )

    # Store the material's mass fraction in the formula.
    weight_fraction: Mapped[float] = mapped_column(
        Float,
        nullable=False,
    )

    # Navigate to the corresponding material record.
    material: Mapped["Material"] = relationship(
        "Material",
        back_populates="bom_items",
    )

    # Navigate to the parent product.
    product: Mapped["Product"] = relationship(
        "Product",
        back_populates="bom_items",
    )
