
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.db.session import get_db
from app.main import app


# Replace the database dependency without opening SQLite.
def override_get_db():
    yield None


# Verify the API returns a valid manufacturing readiness response.
def test_manufacturing_availability_api_success():
    fake_result = {
        "item_code": "TEST-001",
        "item_description": "Synthetic Product",
        "production_quantity": 100,
        "is_ready": False,
        "shortage_count": 1,
        "components": [
            {
                "component_type": "MATERIAL",
                "component_code": "10",
                "component_name": "Test Material",
                "stock_item_id": 101,
                "warehouse_id": 1,
                "unit": "g",
                "required_quantity": "1000",
                "available_quantity": "200",
                "shortage_quantity": "800",
                "surplus_quantity": "0",
                "is_sufficient": False,
            }
        ],
    }

    app.dependency_overrides[get_db] = override_get_db

    try:
        # Mock the service used by the production endpoint.
        with patch(
            "app.api.v1.endpoints.production."
            "check_manufacturing_availability",
            return_value=fake_result,
        ) as mocked_service:

            with TestClient(app) as client:
                response = client.post(
                    "/api/v1/production/availability-check",
                    json={
                        "item_code": "TEST-001",
                        "quantity": 100,
                    },
                )

            assert response.status_code == 200

            data = response.json()

            assert data["is_ready"] is False
            assert data["shortage_count"] == 1
            assert data["components"][0]["shortage_quantity"] == "800"

            mocked_service.assert_called_once_with(
                db=None,
                item_code="TEST-001",
                quantity=100,
            )

    finally:
        app.dependency_overrides.pop(get_db, None)


# Verify that invalid production quantities return HTTP 422.
def test_manufacturing_availability_invalid_quantity():
    app.dependency_overrides[get_db] = override_get_db

    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/v1/production/availability-check",
                json={
                    "item_code": "TEST-001",
                    "quantity": 0,
                },
            )

        assert response.status_code == 422

    finally:
        app.dependency_overrides.pop(get_db, None)


# Verify that unknown products return HTTP 404.
def test_manufacturing_availability_unknown_product():
    app.dependency_overrides[get_db] = override_get_db

    try:
        with patch(
            "app.api.v1.endpoints.production."
            "check_manufacturing_availability",
            side_effect=LookupError("Product not found"),
        ):
            with TestClient(app) as client:
                response = client.post(
                    "/api/v1/production/availability-check",
                    json={
                        "item_code": "UNKNOWN",
                        "quantity": 100,
                    },
                )

        assert response.status_code == 404

    finally:
        app.dependency_overrides.pop(get_db, None)
