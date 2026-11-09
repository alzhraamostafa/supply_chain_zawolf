
from typing import Literal

from pydantic import BaseModel, ConfigDict


# Define and validate the public product response structure.
class ProductResponse(BaseModel):
    item_code: str
    item_description: str
    brand: str
    family: str
    sku_type: str

    unit_volume_ml_gm: float
    packaging_type: str
    product_viscosity: str
    density_sg: float

    # Require one of the supported product size units.
    size_unit: Literal["ml", "gm"]

    # Read attributes directly from SQLAlchemy ORM objects.
    model_config = ConfigDict(from_attributes=True)
