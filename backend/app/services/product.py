
from sqlalchemy.orm import Session

from app.models.product import Product
from app.repositories.product import (
    get_products,
    get_product_by_code,
)


# Retrieve a paginated list of products.

# Retrieve products using validated pagination and optional filters.
def list_products(
    db: Session,
    skip: int = 0,
    limit: int = 20,
    brand: str | None = None,
    family: str | None = None,
    search: str | None = None,
) -> list[Product]:
    # Enforce pagination rules independently of the HTTP layer.
    if skip < 0:
        raise ValueError("skip must be zero or greater")

    if not 1 <= limit <= 100:
        raise ValueError("limit must be between 1 and 100")

    # Normalize optional text filters.
    brand = brand.strip() if brand is not None else None
    family = family.strip() if family is not None else None
    search = search.strip() if search is not None else None

    # Delegate filtering and pagination to the repository.
    return get_products(
    db,
    skip=skip,
    limit=limit,
    brand=brand or None,
    family=family or None,
    search=search or None,
)


# Retrieve product details by item code.
def find_product(
    db: Session,
    item_code: str,
) -> Product | None:
    if not item_code.strip():
        raise ValueError("item_code cannot be empty")

    return get_product_by_code(db, item_code=item_code)
