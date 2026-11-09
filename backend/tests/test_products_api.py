
import sqlite3

from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker
from fastapi.routing import APIRoute

from app.main import app

from app.db.session import create_read_only_engine, get_db
from app.main import app


# Prepare an isolated SQLite database for product API tests.
def test_products_api(tmp_path):
    test_db_path = tmp_path / "products_test.db"

    with sqlite3.connect(test_db_path) as connection:
        connection.execute("""
            CREATE TABLE dim_products (
                item_code TEXT PRIMARY KEY,
                item_description TEXT NOT NULL,
                brand TEXT NOT NULL,
                family TEXT NOT NULL,
                sku_type TEXT NOT NULL,
                unit_volume_ml_gm REAL NOT NULL,
                packaging_type TEXT NOT NULL,
                product_viscosity TEXT NOT NULL,
                density_sg REAL NOT NULL,
                size_unit TEXT NOT NULL
            )
        """)

        # Insert synthetic product data only.
        connection.execute("""
            INSERT INTO dim_products VALUES
            ('TEST-001', 'Test Soap', 'Test Brand',
             'Hand Soap', 'regular', 500.0,
             'Bottle', 'Low', 1.02, 'ml')
        """)

    engine = create_read_only_engine(test_db_path)
    testing_session_factory = sessionmaker(bind=engine)

    # Inject the disposable database into the FastAPI application.
    def override_get_db():
        with testing_session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db

    try:
        with TestClient(app) as client:
            # Verify the products list endpoint.
            response = client.get("/api/v1/products?limit=10")
            assert response.status_code == 200
            assert len(response.json()) == 1
            assert response.json()[0]["size_unit"] == "ml"

            # Verify individual product retrieval.
            response = client.get("/api/v1/products/TEST-001")
            assert response.status_code == 200
            assert response.json()["item_code"] == "TEST-001"

            # Verify an unknown product returns HTTP 404.
            response = client.get("/api/v1/products/UNKNOWN")
            assert response.status_code == 404

            # Verify invalid pagination returns HTTP 422.
            response = client.get("/api/v1/products?limit=0")
            assert response.status_code == 422
    finally:
        app.dependency_overrides.pop(get_db, None)
        engine.dispose()



# Ensure each API path and HTTP method is registered only once.
def test_no_duplicate_api_routes():
    registered_routes = []

    for route in app.routes:
        if isinstance(route, APIRoute):
            for method in route.methods:
                registered_routes.append(
                    (method, route.path)
                )

    assert len(registered_routes) == len(set(registered_routes))