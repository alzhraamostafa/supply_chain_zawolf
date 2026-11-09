import pytest
from pydantic import ValidationError

from app.schemas.product import ProductResponse


# Reject products that contain unsupported measurement units.
def test_product_rejects_invalid_size_unit():
    product_data = {
        "item_code": "TEST-001",
        "item_description": "Test Product",
        "brand": "Test Brand",
        "family": "Body Care",
        "sku_type": "regular",
        "unit_volume_ml_gm": 250.0,
        "packaging_type": "Bottle",
        "product_viscosity": "Low",
        "density_sg": 1.0,
        "size_unit": "kg",
    }

    with pytest.raises(ValidationError):
        ProductResponse.model_validate(product_data)