
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.product import Product


# Retrieve products with optional filters and pagination.
def get_products(
    db: Session,
    skip: int = 0,
    limit: int = 20,
    brand: str | None = None,
    family: str | None = None,
    search: str | None = None,
) -> list[Product]:
    statement = select(Product)

    # Apply exact brand filtering when provided.
    if brand:
        statement = statement.where(Product.brand == brand)

    # Apply exact product family filtering when provided.
    if family:
        statement = statement.where(Product.family == family)

    # Search product descriptions without case sensitivity for Latin letters.
    if search:
        statement = statement.where(
            Product.item_description.icontains(search, autoescape=True)
        )

    # Apply stable ordering before pagination.
    statement = (
        statement
        .order_by(Product.item_code)
        .offset(skip)
        .limit(limit)
    )

    return list(db.scalars(statement).all())


# Retrieve one product using its unique item code.
def get_product_by_code(
    db: Session,
    item_code: str,
) -> Product | None:
    statement = select(Product).where(
        Product.item_code == item_code
    )

    return db.scalar(statement)
