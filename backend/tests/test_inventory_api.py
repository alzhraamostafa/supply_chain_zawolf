
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.db.session import get_db
from app.main import app


# Avoid connecting to the project database during this test.
def override_get_db():
    yield None


# Verify that inventory balances are returned through the API.
def test_inventory_balances_api():
    fake_balances = [
        {
            "stock_item_id": 101,
            "item_name": "Synthetic Material",
            "item_type": "MATERIAL",
            "base_unit": "g",
            "warehouse_id": 1,
            "warehouse_name": "Test Raw Materials Warehouse",
            "current_balance": 25000.0,
        }
    ]

    app.dependency_overrides[get_db] = override_get_db

    try:
        # Mock the service at its import location in the router.
        with patch(
            "app.api.v1.endpoints.inventory."
            "list_inventory_balances",
            return_value=fake_balances,
        ) as mocked_service:
            with TestClient(app) as client:
                response = client.get(
                    "/api/v1/inventory/balances"
                )

            assert response.status_code == 200
            assert len(response.json()) == 1

            item = response.json()[0]

            assert item["stock_item_id"] == 101
            assert item["current_balance"] == 25000.0
            assert item["base_unit"] == "g"

            mocked_service.assert_called_once_with(None)

    finally:
        app.dependency_overrides.pop(get_db, None)
