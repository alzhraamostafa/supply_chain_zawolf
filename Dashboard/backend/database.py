from __future__ import annotations
from pathlib import Path
import sqlite3
from contextlib import contextmanager
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = Path(__import__("os").getenv("SUPPLY_CHAIN_DB", str(PROJECT_ROOT / "data" / "supply_chain.db")))

@contextmanager
def get_connection():
    if not DB_PATH.exists():
        raise FileNotFoundError(f"SQLite database not found: {DB_PATH}")
    conn = sqlite3.connect(str(DB_PATH), timeout=20)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only = ON")
    try:
        yield conn
    finally:
        conn.close()

def query_records(sql: str, params: tuple[Any, ...] = ()) -> list[dict]:
    with get_connection() as conn:
        return [dict(row) for row in conn.execute(sql, params).fetchall()]

def scalar(sql: str, params: tuple[Any, ...] = ()):
    rows = query_records(sql, params)
    return next(iter(rows[0].values()), None) if rows else None

def object_exists(name: str, object_type: str | None = None) -> bool:
    sql = "SELECT 1 FROM sqlite_master WHERE name = ?"
    params: tuple = (name,)
    if object_type:
        sql += " AND type = ?"
        params += (object_type,)
    return bool(query_records(sql, params))

def columns_for(name: str) -> set[str]:
    # name is only called with constants in this project.
    with get_connection() as conn:
        return {row["name"] for row in conn.execute(f'PRAGMA table_info("{name}")')}
