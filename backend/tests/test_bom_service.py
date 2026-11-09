
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.services.bom import calculate_material_requirements


# Build a synthetic product without accessing SQLite.
def make_test_product(size_unit="ml", density=1.02):
    material = SimpleNamespace(
        base_unit="g",
        material_name="Test Material",
    )

    bom_item = SimpleNamespace(
        material_id=1,
        material=material,
        weight_fraction=0.25,
    )

    second_material = SimpleNamespace(
        base_unit="g",
        material_name="Second Material",
    )

    second_bom_item = SimpleNamespace(
        material_id=2,
        material=second_material,
        weight_fraction=0.75,
    )

    packaging_item = SimpleNamespace(
        packaging_sku="TEST-BOTTLE",
        quantity_per_piece=1,
        packaging=SimpleNamespace(
            packaging_type="PRIMARY",
            base_unit="pcs",
        ),
    )

    return SimpleNamespace(
        item_code="TEST-001",
        item_description="Synthetic Test Product",
        unit_volume_ml_gm=250,
        density_sg=density,
        size_unit=size_unit,
        bom_items=[bom_item, second_bom_item],
        packaging_items=[packaging_item],
    )


# Verify volume-to-mass conversion and BOM calculations.
def test_requirements_for_ml_product():
    product = make_test_product()

    with patch(
        "app.services.bom.get_product_bom",
        return_value=product,
    ):
        result = calculate_material_requirements(
            db=None,
            item_code="TEST-001",
            quantity=1000,
        )

    assert Decimal(result["total_mass_g"]) == Decimal("255000")
    assert Decimal(
        result["materials"][0]["required_quantity"]
    ) == Decimal("63750")
    assert result["packaging"][0]["required_quantity"] == 1000


# Verify gram-based products do not apply density again.
def test_requirements_for_gm_product():
    product = make_test_product(size_unit="gm")

    with patch(
        "app.services.bom.get_product_bom",
        return_value=product,
    ):
        result = calculate_material_requirements(
            db=None,
            item_code="TEST-001",
            quantity=1000,
        )

    assert Decimal(result["total_mass_g"]) == Decimal("250000")


# Reject zero or negative production quantities.
@pytest.mark.parametrize("quantity", [0, -1])
def test_rejects_invalid_quantity(quantity):
    with pytest.raises(ValueError):
        calculate_material_requirements(
            db=None,
            item_code="TEST-001",
            quantity=quantity,
        )


# Reject missing products.
def test_rejects_unknown_product():
    with patch(
        "app.services.bom.get_product_bom",
        return_value=None,
    ):
        with pytest.raises(LookupError):
            calculate_material_requirements(
                db=None,
                item_code="UNKNOWN",
                quantity=100,
            )
