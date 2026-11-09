
import sqlite3
from functools import lru_cache
from pathlib import Path
from typing import Generator
from urllib.parse import quote

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import BACKEND_DIR, get_settings


# Resolve the configured SQLite file without creating a new database.
def get_database_path() -> Path:
    settings = get_settings()
    path = Path(settings.database_path)

    if not path.is_absolute():
        path = BACKEND_DIR / path

    path = path.resolve()

    if not path.is_file():
        raise FileNotFoundError(
            f"SQLite database not found: {path}"
        )

    return path


# Create a read-only engine for the existing project database.
def create_read_only_engine(database_path: Path) -> Engine:
    path = database_path.resolve()

    if not path.is_file():
        raise FileNotFoundError(path)

    uri_path = quote(path.as_posix(), safe="/:")
    sqlite_uri = f"file:{uri_path}?mode=ro"

    return create_engine(
        "sqlite+pysqlite://",
        creator=lambda: sqlite3.connect(
            sqlite_uri,
            uri=True,
            timeout=5,
        ),
    )


# Reuse one engine instead of recreating its connection pool per request.
@lru_cache(maxsize=1)
def get_engine() -> Engine:
    return create_read_only_engine(get_database_path())


# Create short-lived sessions using the shared engine.
def get_session_factory():
    return sessionmaker(
        bind=get_engine(),
        autoflush=False,
        expire_on_commit=False,
    )


# Provide one database session per API request and close it afterward.
def get_db() -> Generator[Session, None, None]:
    session = get_session_factory()()

    try:
        yield session
    finally:
        session.close()
