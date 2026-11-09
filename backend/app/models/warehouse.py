
from sqlalchemy import Integer, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base


# Represent a warehouse used by the inventory system.
class Warehouse(Base):
    __tablename__ = "warehouses"

    warehouse_id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
    )

    warehouse_name: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    warehouse_type: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    # Access inventory movements recorded in this warehouse.
    movements: Mapped[list["InventoryMovement"]] = relationship(
    "InventoryMovement",
    back_populates="warehouse",
    )
