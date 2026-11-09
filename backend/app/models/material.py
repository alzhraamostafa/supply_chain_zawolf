
from sqlalchemy import Integer, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


# Map the raw materials catalog to an ORM model.
class Material(Base):
    __tablename__ = "materials"

    material_id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
    )

    material_name: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    base_unit: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    # Access BOM lines that reference this material.
    bom_items: Mapped[list["ProductBOMItem"]] = relationship(
        "ProductBOMItem",
        back_populates="material",
    )
