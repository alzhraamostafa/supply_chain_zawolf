"""Copy every table from a SQLite file into another database, verify row counts, and log the load.
Works with any DB-API connection. dialect is "postgres" or "sqlite" (sqlite is used in tests)."""
import hashlib
import sqlite3
from datetime import datetime, timezone

PG_TYPES = (("INT", "BIGINT"), ("REAL", "DOUBLE PRECISION"), ("FLOA", "DOUBLE PRECISION"),
            ("DOUB", "DOUBLE PRECISION"), ("NUM", "NUMERIC"), ("DEC", "NUMERIC"), ("BOOL", "SMALLINT"))


def pg_type(sqlite_type: str) -> str:
    t = (sqlite_type or "").upper()
    for key, pg in PG_TYPES:
        if key in t:
            return pg
    return "TEXT"


def quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def qualified(table: str, dialect: str) -> str:
    return f"raw.{quote(table)}" if dialect == "postgres" else quote(table)


def placeholder(dialect: str) -> str:
    return "%s" if dialect == "postgres" else "?"


def create_table_sql(table: str, columns: list[tuple[str, str]], dialect: str) -> str:
    cols = ", ".join(
        f"{quote(name)} {pg_type(t) if dialect == 'postgres' else (t or 'TEXT')}" for name, t in columns)
    return f"CREATE TABLE {qualified(table, dialect)} ({cols})"


def sha256_of(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _copy(src, src_path: str, dst, dialect: str) -> list[dict]:
    """Replace every table in dst with a copy of the SQLite file. Returns one result per table."""
    digest = sha256_of(src_path)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    ph = placeholder(dialect)
    log = qualified("etl_load_log", dialect)
    cur = dst.cursor()
    if dialect == "postgres":
        cur.execute("CREATE SCHEMA IF NOT EXISTS raw")
    cur.execute(f"CREATE TABLE IF NOT EXISTS {log} (loaded_at TEXT, source_file TEXT, "
                "source_sha256 TEXT, table_name TEXT, rows_source BIGINT, rows_loaded BIGINT)")
    tables = [r[0] for r in src.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite\\_%' ESCAPE '\\' ORDER BY name")]
    results = []
    for t in tables:
        columns = [(r[1], r[2]) for r in src.execute(f"PRAGMA table_info({quote(t)})")]
        cur.execute(f"DROP TABLE IF EXISTS {qualified(t, dialect)}")
        cur.execute(create_table_sql(t, columns, dialect))
        rows = src.execute(f"SELECT * FROM {quote(t)}").fetchall()
        if rows:
            marks = ", ".join([ph] * len(columns))
            cur.executemany(f"INSERT INTO {qualified(t, dialect)} VALUES ({marks})", rows)
        cur.execute(f"SELECT COUNT(*) FROM {qualified(t, dialect)}")
        n_dst = cur.fetchone()[0]
        cur.execute(f"INSERT INTO {log} VALUES ({', '.join([ph] * 6)})",
                    (now, src_path.replace("\\", "/").split("/")[-1], digest, t, len(rows), n_dst))
        results.append({"table": t, "rows_source": len(rows), "rows_loaded": n_dst,
                        "ok": len(rows) == n_dst})
    dst.commit()
    return results


def load(src_path: str, dst, dialect: str) -> list[dict]:
    """Replace every table in dst with a copy of the SQLite file. Always closes the source file."""
    src = sqlite3.connect(f"file:{src_path}?mode=ro", uri=True)
    try:
        return _copy(src, src_path, dst, dialect)
    finally:
        src.close()
