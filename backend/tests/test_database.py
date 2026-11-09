
import sqlite3

from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from app.db.session import create_read_only_engine, get_db
from app.main import app


# Test database connectivity without accessing the project database.
def test_database_info(tmp_path):
    test_db_path = tmp_path / "test.db"

    # Create a disposable SQLite database with one table.
    with sqlite3.connect(test_db_path) as connection:
        connection.execute(
            "CREATE TABLE example (id INTEGER PRIMARY KEY)"
        )

    engine = create_read_only_engine(test_db_path)
    test_session_factory = sessionmaker(bind=engine)

    # Replace the real database dependency with the test database.
    def override_get_db():
        with test_session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db

    try:
        with TestClient(app) as client:
            response = client.get("/api/v1/database/info")

        assert response.status_code == 200
        assert response.json() == {
            "status": "connected",
            "table_count": 1,
        }

        # Verify that read-only connections reject database writes.
        with Session(engine) as session:
            try:
                session.execute(
                    text("INSERT INTO example (id) VALUES (1)")
                )
                session.commit()
                raise AssertionError("Read-only database accepted a write")
            except Exception as exc:
                if isinstance(exc, AssertionError):
                    raise
                session.rollback()
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
