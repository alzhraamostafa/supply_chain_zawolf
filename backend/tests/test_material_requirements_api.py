
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.db.session import get_db
from app.main import app


# Provide a fake database dependency without opening SQLite.
def override_get_db():
    yield None


# Verify that the API returns a validated calculation response.
def test_material_requirements_success():
    fake_result = {
        "item_code": "TEST-001",
        "item_description": "Synthetic Test Product",
        "production_quantity": 100,
        "mass_per_piece_g": "250",
        "total_mass_g": "25000",
        "materials": [
            {
                "material_id": 1,
                "material_name": "Test Material",
                "weight_fraction": "1",
                "required_quantity": "25000",
                "unit": "g",
            }
        ],
        "packaging": [
            {
                "packaging_sku": "TEST-BOTTLE",
                "packaging_type": "PRIMARY",
                "required_quantity": 100,
                "unit": "pcs",
            }
        ],
    }

    app.dependency_overrides[get_db] = override_get_db

    try:
        # Mock the service where the endpoint imports it.
        with patch(
            "app.api.v1.endpoints.production.calculate_material_requirements",
            return_value=fake_result,
        ) as mocked_service:
            with TestClient(app) as client:
                response = client.post(
                    "/api/v1/production/material-requirements",
                    json={
                        "item_code": "TEST-001",
                        "quantity": 100,
                    },
                )

            assert response.status_code == 200
            assert response.json()["total_mass_g"] == "25000"
            assert response.json()["materials"][0]["unit"] == "g"

            mocked_service.assert_called_once_with(
                db=None,
                item_code="TEST-001",
                quantity=100,
            )
    finally:
        app.dependency_overrides.pop(get_db, None)


# Verify that invalid production quantities are rejected.
def test_material_requirements_invalid_quantity():
    app.dependency_overrides[get_db] = override_get_db

    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/v1/production/material-requirements",
                json={
                    "item_code": "TEST-001",
                    "quantity": 0,
                },
            )

        assert response.status_code == 422
    finally:
        app.dependency_overrides.pop(get_db, None)


# Verify that unknown products return an HTTP 404.
def test_material_requirements_unknown_product():
    app.dependency_overrides[get_db] = override_get_db

    try:
        with patch(
            "app.api.v1.endpoints.production.calculate_material_requirements",
            side_effect=LookupError("Product not found"),
        ):
            with TestClient(app) as client:
                response = client.post(
                    "/api/v1/production/material-requirements",
                    json={
                        "item_code": "UNKNOWN",
                        "quantity": 100,
                    },
                )

        assert response.status_code == 404
        assert response.json()["detail"] == "Product not found"
    finally:
        app.dependency_overrides.pop(get_db, None)
