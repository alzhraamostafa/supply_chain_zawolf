
from decimal import Decimal

from sqlalchemy.orm import Session

from app.repositories.bom import get_product_bom


# Convert database numeric values to Decimal consistently.
def to_decimal(value: int | float) -> Decimal:
    return Decimal(str(value))


# Calculate theoretical manufacturing material requirements.
def calculate_material_requirements(
    db: Session,
    item_code: str,
    quantity: int,
) -> dict:
    # Require a positive whole-number production quantity.
    if type(quantity) is not int or quantity <= 0:
        raise ValueError("Production quantity must be a positive integer")

    # Retrieve the product and all its BOM components.
    product = get_product_bom(db, item_code)

    if product is None:
        raise LookupError("Product not found")

    if not product.bom_items:
        raise ValueError("Product has no raw material BOM")

    if not product.packaging_items:
        raise ValueError("Product has no packaging BOM")

    nominal_size = to_decimal(product.unit_volume_ml_gm)
    density = to_decimal(product.density_sg)

    # Validate the product's physical properties.
    if nominal_size <= 0:
        raise ValueError("Product size must be positive")

    if product.size_unit == "ml":
        if density <= 0:
            raise ValueError("Product density must be positive")

        # Convert volume in milliliters to mass in grams.
        mass_per_piece_g = nominal_size * density

    elif product.size_unit == "gm":
        # The nominal size already represents grams.
        mass_per_piece_g = nominal_size

    else:
        raise ValueError("Unsupported product size unit")

    total_mass_g = mass_per_piece_g * quantity

    # Validate the total mass fraction of the product formula.
    total_fraction = sum(
        (
            to_decimal(item.weight_fraction)
            for item in product.bom_items
        ),
        Decimal("0"),
    )

    if abs(total_fraction - Decimal("1")) > Decimal("0.000001"):
        raise ValueError("BOM fractions must sum to 1")

    materials = []

    for item in product.bom_items:
        if item.material.base_unit != "g":
            raise ValueError("Unsupported raw material unit")

        fraction = to_decimal(item.weight_fraction)

        if fraction <= 0 or fraction > 1:
            raise ValueError("Invalid material weight fraction")

        required_g = total_mass_g * fraction

        materials.append({
            "material_id": item.material_id,
            "material_name": item.material.material_name,
            "weight_fraction": str(fraction),
            "required_quantity": str(required_g),
            "unit": "g",
        })

    packaging = []

    for item in product.packaging_items:
        if item.packaging.base_unit != "pcs":
            raise ValueError("Unsupported packaging unit")

        if item.quantity_per_piece <= 0:
            raise ValueError("Invalid packaging quantity")

        packaging.append({
            "packaging_sku": item.packaging_sku,
            "packaging_type": item.packaging.packaging_type,
            "required_quantity": quantity * item.quantity_per_piece,
            "unit": "pcs",
        })

    # Return calculated requirements without writing to the database.
    return {
        "item_code": product.item_code,
        "item_description": product.item_description,
        "production_quantity": quantity,
        "mass_per_piece_g": str(mass_per_piece_g),
        "total_mass_g": str(total_mass_g),
        "materials": materials,
        "packaging": packaging,
    }


# Return the complete product BOM without calculating batch quantities.
def get_bom_details(
    db: Session,
    item_code: str,
) -> dict:
    product = get_product_bom(db, item_code)

    if product is None:
        raise LookupError("Product not found")

    materials = [
        {
            "material_id": item.material_id,
            "material_name": item.material.material_name,
            "weight_fraction": item.weight_fraction,
            "base_unit": item.material.base_unit,
        }
        for item in sorted(
            product.bom_items,
            key=lambda item: item.material_id,
        )
    ]

    packaging = [
        {
            "packaging_sku": item.packaging_sku,
            "packaging_type": item.packaging.packaging_type,
            "quantity_per_piece": item.quantity_per_piece,
            "base_unit": item.packaging.base_unit,
        }
        for item in sorted(
            product.packaging_items,
            key=lambda item: item.packaging_sku,
        )
    ]

    return {
        "item_code": product.item_code,
        "item_description": product.item_description,
        "size_unit": product.size_unit,
        "unit_volume_ml_gm": product.unit_volume_ml_gm,
        "density_sg": product.density_sg,
        "materials": materials,
        "packaging": packaging,
    }
