
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
# Import the manufacturing readiness response schema.
from app.schemas.bom import ManufacturingAvailabilityResponse

# Import the manufacturing availability business service.
from app.services.manufacturing_availability import (
    check_manufacturing_availability,
)

from app.db.session import get_db
from app.schemas.bom import (
    MaterialRequirementsRequest,
    MaterialRequirementsResponse,
)
from app.services.bom import calculate_material_requirements


# Group production-related endpoints under one router.
router = APIRouter(prefix="/production", tags=["Production"])


# Calculate theoretical material requirements without changing inventory.
@router.post(
    "/material-requirements",
    response_model=MaterialRequirementsResponse,
)
def calculate_requirements_endpoint(
    request: MaterialRequirementsRequest,
    db: Annotated[Session, Depends(get_db)],
):
    try:
        return calculate_material_requirements(
            db=db,
            item_code=request.item_code,
            quantity=request.quantity,
        )

    except LookupError as exc:
        # Return 404 when the requested product does not exist.
        raise HTTPException(
            status_code=404,
            detail=str(exc),
        ) from exc

    except ValueError as exc:
        # Return 400 when stored business data is invalid.
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc



# Check whether inventory can cover a proposed manufacturing batch.
@router.post(
    "/availability-check",
    response_model=ManufacturingAvailabilityResponse,
)
def check_production_availability_endpoint(
    request: MaterialRequirementsRequest,
    db: Annotated[Session, Depends(get_db)],
):
    try:
        # Calculate requirements and compare them against stock balances.
        return check_manufacturing_availability(
            db=db,
            item_code=request.item_code,
            quantity=request.quantity,
        )

    except LookupError as exc:
        # Return 404 if the product does not exist.
        raise HTTPException(
            status_code=404,
            detail=str(exc),
        ) from exc

    except ValueError as exc:
        # Report invalid manufacturing data or configuration.
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc
