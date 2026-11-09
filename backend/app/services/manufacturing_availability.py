
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Warehouse
from app.repositories.inventory import (
    get_stock_item_by_material,
    get_stock_item_by_packaging,
)
from app.services.bom import calculate_material_requirements
from app.services.inventory import check_stock_availability


# Calculate manufacturing readiness without changing stock.
def check_manufacturing_availability(
    db: Session,
    item_code: str,
    quantity: int,
) -> dict:
    # Calculate theoretical raw material and packaging needs.
    requirements = calculate_material_requirements(
        db=db,
        item_code=item_code,
        quantity=quantity,
    )

    # Find the warehouse used for raw materials and packaging.
    warehouse = db.scalar(
        select(Warehouse).where(
            Warehouse.warehouse_type == "RAW_MATERIALS"
        )
    )

    if warehouse is None:
        raise ValueError("Raw materials warehouse is not configured")

    components = []

    # Check raw material availability.
    for material in requirements["materials"]:
        stock_item = get_stock_item_by_material(
            db=db,
            material_id=material["material_id"],
        )

        if stock_item is None:
            raise ValueError(
                f"Missing stock mapping for material "
                f"{material['material_id']}"
            )

        if stock_item.base_unit != material["unit"]:
            raise ValueError("Raw material unit mismatch")

        availability = check_stock_availability(
            db=db,
            stock_item_id=stock_item.stock_item_id,
            warehouse_id=warehouse.warehouse_id,
            required_quantity=material["required_quantity"],
        )

        components.append({
            "component_type": "MATERIAL",
            "component_code": str(material["material_id"]),
            "component_name": material["material_name"],
            "stock_item_id": stock_item.stock_item_id,
            "unit": material["unit"],
            **availability,
        })

    # Check packaging availability.
    for packaging in requirements["packaging"]:
        stock_item = get_stock_item_by_packaging(
            db=db,
            packaging_sku=packaging["packaging_sku"],
        )

        if stock_item is None:
            raise ValueError(
                f"Missing stock mapping for packaging "
                f"{packaging['packaging_sku']}"
            )

        if stock_item.base_unit != packaging["unit"]:
            raise ValueError("Packaging unit mismatch")

        availability = check_stock_availability(
            db=db,
            stock_item_id=stock_item.stock_item_id,
            warehouse_id=warehouse.warehouse_id,
            required_quantity=packaging["required_quantity"],
        )

        components.append({
            "component_type": "PACKAGING",
            "component_code": packaging["packaging_sku"],
            "component_name": packaging["packaging_sku"],
            "stock_item_id": stock_item.stock_item_id,
            "unit": packaging["unit"],
            **availability,
        })

    # Production is ready only when every component has enough stock.
    is_ready = all(
        component["is_sufficient"]
        for component in components
    )

    # Count components with a positive shortage.
    shortage_count = sum(
        Decimal(component["shortage_quantity"]) > 0
        for component in components
    )

    return {
        "item_code": requirements["item_code"],
        "item_description": requirements["item_description"],
        "production_quantity": requirements["production_quantity"],
        "is_ready": is_ready,
        "shortage_count": shortage_count,
        "components": components,
    }
