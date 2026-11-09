
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from app.services.manufacturing_availability import (
    check_manufacturing_availability,
)


# Define synthetic manufacturing requirements.
def make_requirements():
    return {
        "item_code": "TEST-001",
        "item_description": "Test Product",
        "production_quantity": 100,
        "materials": [
            {
                "material_id": 10,
                "material_name": "Material A",
                "required_quantity": "1000",
                "unit": "g",
            },
            {
                "material_id": 20,
                "material_name": "Material B",
                "required_quantity": "500",
                "unit": "g",
            },
        ],
        "packaging": [
            {
                "packaging_sku": "TEST-BOTTLE",
                "required_quantity": 100,
                "unit": "pcs",
            },
        ],
    }


# Run the service with controlled, synthetic inventory balances.
def run_availability_check(balances):
    # Simulate the configured raw materials warehouse.
    db = Mock()
    db.scalar.return_value = SimpleNamespace(warehouse_id=1)

    # Create inventory mappings with intentionally different IDs.
    material_items = {
        10: SimpleNamespace(stock_item_id=101, base_unit="g"),
        20: SimpleNamespace(stock_item_id=102, base_unit="g"),
    }

    packaging_items = {
        "TEST-BOTTLE": SimpleNamespace(
            stock_item_id=201,
            base_unit="pcs",
        ),
    }

    # Return the matching stock item for each material.
    def find_material(db, material_id):
        return material_items.get(material_id)

    # Return the matching stock item for each packaging component.
    def find_packaging(db, packaging_sku):
        return packaging_items.get(packaging_sku)

    # Simulate stock availability using supplied balances.
    def fake_stock_availability(
        db, stock_item_id, warehouse_id, required_quantity
    ):
        required = Decimal(str(required_quantity))
        available = Decimal(str(balances.get(stock_item_id, 0)))

        return {
            "stock_item_id": stock_item_id,
            "warehouse_id": warehouse_id,
            "required_quantity": str(required),
            "available_quantity": str(available),
            "shortage_quantity": str(max(required - available, 0)),
            "surplus_quantity": str(max(available - required, 0)),
            "is_sufficient": available >= required,
        }

    # Replace external dependencies only during this test.
    with (
        patch(
            "app.services.manufacturing_availability."
            "calculate_material_requirements",
            return_value=make_requirements(),
        ),
        patch(
            "app.services.manufacturing_availability."
            "get_stock_item_by_material",
            side_effect=find_material,
        ),
        patch(
            "app.services.manufacturing_availability."
            "get_stock_item_by_packaging",
            side_effect=find_packaging,
        ),
        patch(
            "app.services.manufacturing_availability."
            "check_stock_availability",
            side_effect=fake_stock_availability,
        ),
    ):
        return check_manufacturing_availability(
            db=db,
            item_code="TEST-001",
            quantity=100,
        )


# Check readiness under different inventory conditions.
@pytest.mark.parametrize(
    "balances, expected_ready, expected_shortages",
    [
        ({}, False, 3),
        ({101: 1000, 102: 200, 201: 100}, False, 1),
        ({101: 1000, 102: 500, 201: 100}, True, 0),
    ],
)
def test_manufacturing_readiness(
    balances,
    expected_ready,
    expected_shortages,
):
    result = run_availability_check(balances)

    assert result["is_ready"] is expected_ready
    assert result["shortage_count"] == expected_shortages
    assert len(result["components"]) == 3


# Reject an incomplete mapping instead of treating it as zero stock.
def test_missing_material_mapping():
    db = Mock()
    db.scalar.return_value = SimpleNamespace(warehouse_id=1)

    with (
        patch(
            "app.services.manufacturing_availability."
            "calculate_material_requirements",
            return_value=make_requirements(),
        ),
        patch(
            "app.services.manufacturing_availability."
            "get_stock_item_by_material",
            return_value=None,
        ),
    ):
        with pytest.raises(ValueError, match="Missing stock mapping"):
            check_manufacturing_availability(
                db=db,
                item_code="TEST-001",
                quantity=100,
            )
