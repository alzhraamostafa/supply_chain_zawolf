
import sqlite3

import pytest
from sqlalchemy.orm import Session

from app.db.session import create_read_only_engine
from app.repositories.inventory import (
    get_all_stock_balances,
    get_stock_balance,
)

# Register ORM models and relationships before executing queries.
import app.models


@pytest.fixture
def inventory_db(tmp_path):
    # Create an isolated test database.
    database_path = tmp_path / "inventory_test.db"

    with sqlite3.connect(database_path) as connection:
        # Create the minimal tables required for the repository queries.
        connection.executescript("""
            CREATE TABLE stock_items (
                stock_item_id INTEGER PRIMARY KEY,
                item_name TEXT NOT NULL,
                item_type TEXT NOT NULL,
                material_id INTEGER,
                packaging_sku TEXT,
                product_item_code TEXT,
                base_unit TEXT NOT NULL
            );

            CREATE TABLE warehouses (
                warehouse_id INTEGER PRIMARY KEY,
                warehouse_name TEXT NOT NULL,
                warehouse_type TEXT NOT NULL
            );

            CREATE TABLE inventory_movements (
                movement_id INTEGER PRIMARY KEY,
                stock_item_id INTEGER NOT NULL,
                warehouse_id INTEGER NOT NULL,
                movement_type TEXT NOT NULL,
                quantity_delta REAL NOT NULL,
                source_document_type TEXT,
                source_document_id INTEGER,
                movement_date TEXT NOT NULL
            );

            INSERT INTO stock_items
                (stock_item_id, item_name, item_type, base_unit)
            VALUES
                (1, 'Test Material', 'MATERIAL', 'g'),
                (2, 'Unused Material', 'MATERIAL', 'g');

            INSERT INTO warehouses
                (warehouse_id, warehouse_name, warehouse_type)
            VALUES
                (1, 'Raw Materials Warehouse', 'RAW_MATERIALS'),
                (2, 'Finished Goods Warehouse', 'FINISHED_GOODS');

            INSERT INTO inventory_movements
                (stock_item_id, warehouse_id, movement_type,
                 quantity_delta, movement_date)
            VALUES
                (1, 1, 'PURCHASE_RECEIPT', 50000, '2026-01-01'),
                (1, 1, 'PRODUCTION_ISSUE', -12000, '2026-01-02'),
                (1, 1, 'ADJUSTMENT', 2000, '2026-01-03');
        """)

    # Reopen the prepared test database in read-only mode.
    engine = create_read_only_engine(database_path)

    try:
        with Session(engine) as session:
            yield session
    finally:
        engine.dispose()


# Verify signed movements are aggregated correctly.
def test_stock_balance_calculation(inventory_db):
    balance = get_stock_balance(
        inventory_db,
        stock_item_id=1,
        warehouse_id=1,
    )

    assert balance == 40000.0


# Verify items without movements start with zero balance.
def test_zero_opening_balance(inventory_db):
    balance = get_stock_balance(
        inventory_db,
        stock_item_id=2,
        warehouse_id=1,
    )

    assert balance == 0.0


# Verify all items are included in the stock balance listing.
def test_all_stock_balances(inventory_db):
    balances = get_all_stock_balances(inventory_db)

    assert len(balances) == 2

    by_id = {
        item["stock_item_id"]: item
        for item in balances
    }

    assert by_id[1]["current_balance"] == 40000.0
    assert by_id[2]["current_balance"] == 0.0

    assert by_id[1]["warehouse_name"] == "Raw Materials Warehouse"
