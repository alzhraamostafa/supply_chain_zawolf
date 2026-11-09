
from decimal import Decimal

from sqlalchemy.orm import Session

from app.repositories.inventory import get_stock_balance
# Import the inventory balance repository query.
from app.repositories.inventory import get_all_stock_balances

# Convert numeric values to Decimal for consistent calculations.
def to_decimal(value: int | float | str) -> Decimal:
    return Decimal(str(value))


# Compare a stock item's recorded balance with a requested quantity.
def check_stock_availability(
    db: Session,
    stock_item_id: int,
    warehouse_id: int,
    required_quantity: int | float | str,
) -> dict:
    required = to_decimal(required_quantity)

    # Reject invalid or negative requested quantities.
    if not required.is_finite() or required < 0:
        raise ValueError("Required quantity must be non-negative and finite")

    # Read the recorded balance from the inventory repository.
    current_balance = to_decimal(
        get_stock_balance(
            db=db,
            stock_item_id=stock_item_id,
            warehouse_id=warehouse_id,
        )
    )

    # Detect invalid ledger balances before calculating availability.
    if not current_balance.is_finite() or current_balance < 0:
        raise ValueError("Invalid inventory balance")

    # Calculate shortages and remaining stock independently.
    shortage = max(required - current_balance, Decimal("0"))
    surplus = max(current_balance - required, Decimal("0"))

    return {
        "stock_item_id": stock_item_id,
        "warehouse_id": warehouse_id,
        "required_quantity": str(required),
        "available_quantity": str(current_balance),
        "shortage_quantity": str(shortage),
        "surplus_quantity": str(surplus),
        "is_sufficient": current_balance >= required,
    }



# Retrieve validated operational inventory balances.
def list_inventory_balances(db: Session) -> list[dict]:
    balances = get_all_stock_balances(db)

    # Negative balances indicate an invalid operational ledger.
    for item in balances:
        if item["current_balance"] < 0:
            raise ValueError(
                f"Negative balance for stock item "
                f"{item['stock_item_id']}"
            )

    return balances
