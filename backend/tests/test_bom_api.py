
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.db.session import get_db
from app.main import app


# Replace the database dependency with an isolated test dependency.
def override_get_db():
    yield None


# Verify the BOM endpoint returns the expected response structure.
def test_product_bom_endpoint():
    fake_bom = {
        "item_code": "TEST-001",
        "item_description": "Synthetic Test Product",
        "size_unit": "ml",
        "unit_volume_ml_gm": 250.0,
        "density_sg": 1.02,
        "materials": [
            {
                "material_id": 1,
                "material_name": "Test Material",
                "weight_fraction": 1.0,
                "base_unit": "g",
            }
        ],
        "packaging": [
            {
                "packaging_sku": "TEST-BOTTLE",
                "packaging_type": "PRIMARY",
                "quantity_per_piece": 1,
                "base_unit": "pcs",
            }
        ],
    }

    app.dependency_overrides[get_db] = override_get_db

    try:
        with patch(
            "app.api.v1.endpoints.products.get_bom_details",
            return_value=fake_bom,
        ):
            with TestClient(app) as client:
                response = client.get(
                    "/api/v1/products/TEST-001/bom"
                )

        assert response.status_code == 200
        assert response.json()["item_code"] == "TEST-001"
        assert len(response.json()["materials"]) == 1
        assert response.json()["packaging"][0]["quantity_per_piece"] == 1

    finally:
        app.dependency_overrides.pop(get_db, None)
