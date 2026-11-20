"""Database helpers. The agent writes ONLY to simulation tables, always inside a transaction."""
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

def connect(path: str) -> sqlite3.Connection:
    con = sqlite3.connect(path, isolation_level=None)   # we control transactions
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    return con

def now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")

@contextmanager
def tx(con):
    con.execute("BEGIN IMMEDIATE")
    try:
        yield con
        con.execute("COMMIT")
    except BaseException:
        con.execute("ROLLBACK")
        raise
