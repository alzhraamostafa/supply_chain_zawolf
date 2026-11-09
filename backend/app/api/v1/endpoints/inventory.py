
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.inventory import InventoryBalanceResponse
from app.services.inventory import list_inventory_balances


# Group inventory endpoints under one API router.
router = APIRouter(
    prefix="/inventory",
    tags=["Inventory"],
)


# Return operational inventory balances for all stock items.
@router.get(
    "/balances",
    response_model=list[InventoryBalanceResponse],
)
def get_inventory_balances_endpoint(
    db: Annotated[Session, Depends(get_db)],
):
    return list_inventory_balances(db)
