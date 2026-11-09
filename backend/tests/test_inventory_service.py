
from decimal import Decimal
from unittest.mock import patch

import pytest

from app.services.inventory import check_stock_availability


# Test inventory shortages with a mocked repository balance.
@pytest.mark.parametrize(
    "available, required, expected_shortage, expected_surplus, sufficient",
    [
        (25000, 50000, 25000, 0, False),
        (25000, 10000, 0, 15000, True),
        (0, 50000, 50000, 0, False),
        (25000, 25000, 0, 0, True),
    ],
)
def test_stock_availability(
    available,
    required,
    expected_shortage,
    expected_surplus,
    sufficient,
):
    # Replace the repository function with a controlled test balance.
    with patch(
        "app.services.inventory.get_stock_balance",
        return_value=available,
    ) as mocked_balance:
        result = check_stock_availability(
            db=None,
            stock_item_id=1,
            warehouse_id=1,
            required_quantity=required,
        )

    assert Decimal(result["shortage_quantity"]) == expected_shortage
    assert Decimal(result["surplus_quantity"]) == expected_surplus
    assert result["is_sufficient"] is sufficient

    mocked_balance.assert_called_once_with(
        db=None,
        stock_item_id=1,
        warehouse_id=1,
    )


# Verify negative requirements are rejected.
def test_rejects_negative_required_quantity():
    with pytest.raises(ValueError):
        check_stock_availability(
            db=None,
            stock_item_id=1,
            warehouse_id=1,
            required_quantity=-5,
        )


# Verify invalid ledger balances are rejected.
def test_rejects_negative_stock_balance():
    with patch(
        "app.services.inventory.get_stock_balance",
        return_value=-100,
    ):
        with pytest.raises(ValueError):
            check_stock_availability(
                db=None,
                stock_item_id=1,
                warehouse_id=1,
                required_quantity=50,
            )
