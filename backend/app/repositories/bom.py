
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import Product, ProductBOMItem, ProductPackagingItem


# Retrieve a product with its full raw-material and packaging BOM.
def get_product_bom(
    db: Session,
    item_code: str,
) -> Product | None:
    statement = (
        select(Product)
        .options(
            # Load raw material BOM lines and material details.
            selectinload(Product.bom_items).selectinload(
                ProductBOMItem.material
            ),

            # Load packaging BOM lines and packaging item details.
            selectinload(Product.packaging_items).selectinload(
                ProductPackagingItem.packaging
            ),
        )
        .where(Product.item_code == item_code)
    )

    return db.scalar(statement)
