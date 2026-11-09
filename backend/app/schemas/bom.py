
from typing import Literal

from pydantic import BaseModel, Field
from typing import Literal

from pydantic import BaseModel

# Validate the input for a manufacturing requirements calculation.
class MaterialRequirementsRequest(BaseModel):
    item_code: str = Field(min_length=1)
    quantity: int = Field(gt=0)


# Describe one raw material requirement.
class RawMaterialRequirement(BaseModel):
    material_id: int
    material_name: str
    weight_fraction: str
    required_quantity: str
    unit: Literal["g"]


# Describe one packaging component requirement.
class PackagingRequirement(BaseModel):
    packaging_sku: str
    packaging_type: str
    required_quantity: int
    unit: Literal["pcs"]


# Define the complete manufacturing calculation response.
class MaterialRequirementsResponse(BaseModel):
    item_code: str
    item_description: str
    production_quantity: int
    mass_per_piece_g: str
    total_mass_g: str
    materials: list[RawMaterialRequirement]
    packaging: list[PackagingRequirement]


# Describe one raw material in the product's formula.
class BOMMaterialItem(BaseModel):
    material_id: int
    material_name: str
    weight_fraction: float
    base_unit: str


# Describe one packaging component per finished product.
class BOMPackagingItem(BaseModel):
    packaging_sku: str
    packaging_type: str
    quantity_per_piece: int
    base_unit: str


# Define the complete product BOM response.
class ProductBOMResponse(BaseModel):
    item_code: str
    item_description: str
    size_unit: Literal["ml", "gm"]
    unit_volume_ml_gm: float
    density_sg: float
    materials: list[BOMMaterialItem]
    packaging: list[BOMPackagingItem]



# Describe stock availability for one manufacturing component.
class ComponentAvailability(BaseModel):
    component_type: Literal["MATERIAL", "PACKAGING"]
    component_code: str
    component_name: str

    stock_item_id: int
    warehouse_id: int
    unit: Literal["g", "pcs"]

    required_quantity: str
    available_quantity: str
    shortage_quantity: str
    surplus_quantity: str
    is_sufficient: bool


# Define the complete manufacturing readiness response.
class ManufacturingAvailabilityResponse(BaseModel):
    item_code: str
    item_description: str
    production_quantity: int

    is_ready: bool
    shortage_count: int
    components: list[ComponentAvailability]
