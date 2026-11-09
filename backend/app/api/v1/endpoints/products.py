
from typing import Annotated

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    status,
)
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.product import ProductResponse
from app.schemas.bom import ProductBOMResponse
from app.services.product import (
    find_product,
    list_products,
)
from app.services.bom import get_bom_details


# Group all product-related endpoints under one router.
router = APIRouter(
    prefix="/products",
    tags=["Products"],
)


# ---------------------------------------------------------
# GET /api/v1/products
# Retrieve products with optional filtering and pagination.
# ---------------------------------------------------------
@router.get(
    "",
    response_model=list[ProductResponse],
)
def get_products_endpoint(
    db: Annotated[Session, Depends(get_db)],
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    brand: str | None = None,
    family: str | None = None,
    search: str | None = None,
):
    return list_products(
        db=db,
        skip=skip,
        limit=limit,
        brand=brand,
        family=family,
        search=search,
    )


# ---------------------------------------------------------
# GET /api/v1/products/{item_code}/bom
# Retrieve the raw material and packaging BOM of a product.
# ---------------------------------------------------------
@router.get(
    "/{item_code}/bom",
    response_model=ProductBOMResponse,
)
def get_product_bom_endpoint(
    item_code: str,
    db: Annotated[Session, Depends(get_db)],
):
    try:
        return get_bom_details(
            db=db,
            item_code=item_code,
        )

    except LookupError as exc:
        # Return HTTP 404 when the product does not exist.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


# ---------------------------------------------------------
# GET /api/v1/products/{item_code}
# Retrieve the details of one product by its item code.
# ---------------------------------------------------------
@router.get(
    "/{item_code}",
    response_model=ProductResponse,
)
def get_product_endpoint(
    item_code: str,
    db: Annotated[Session, Depends(get_db)],
):
    product = find_product(
        db=db,
        item_code=item_code,
    )

    if product is None:
        # Return HTTP 404 when the product is not found.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found",
        )

    return product
