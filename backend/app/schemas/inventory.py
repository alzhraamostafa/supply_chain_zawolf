
from typing import Literal

from pydantic import BaseModel, Field


# Define the API response for one inventory balance.
class InventoryBalanceResponse(BaseModel):
    stock_item_id: int
    item_name: str

    item_type: Literal[
        "MATERIAL",
        "PACKAGING",
        "FINISHED_PRODUCT",
    ]

    base_unit: Literal["g", "pcs"]

    warehouse_id: int
    warehouse_name: str

    # Validate that the returned quantity is a finite number.
    current_balance: float = Field(allow_inf_nan=False)
