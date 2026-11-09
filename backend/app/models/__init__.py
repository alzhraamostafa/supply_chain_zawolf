# Register all current ORM models and their relationships.
from app.models.product import Product
from app.models.material import Material
from app.models.product_bom import ProductBOMItem
from app.models.packaging import PackagingItem, ProductPackagingItem
# Register the inventory catalog ORM models.
from app.models.stock_item import StockItem
from app.models.warehouse import Warehouse
# Register the inventory movement ORM model.
from app.models.inventory_movement import InventoryMovement
