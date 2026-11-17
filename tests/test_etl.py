import os
import sqlite3
import tempfile

from etl.loader import create_table_sql, load, pg_type, quote


def make_source(path):
    con = sqlite3.connect(path)
    con.executescript("""
        CREATE TABLE items (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, price REAL);
        CREATE TABLE empty_table (x INTEGER);
    """)
    con.executemany("INSERT INTO items (name, price) VALUES (?, ?)", [("a", 1.5), ("b", 2.5), ("c", None)])
    con.commit()
    con.close()


def test_pg_type_mapping():
    assert pg_type("INTEGER") == "BIGINT"
    assert pg_type("REAL") == "DOUBLE PRECISION"
    assert pg_type("DECIMAL(10,2)") == "NUMERIC"
    assert pg_type("BOOLEAN") == "SMALLINT"
    assert pg_type("VARCHAR(20)") == "TEXT"
    assert pg_type("DATE") == "TEXT"
    assert pg_type("") == "TEXT"


def test_quote_escapes_double_quotes():
    assert quote('we"ird') == '"we""ird"'


def test_create_table_sql_for_postgres():
    sql = create_table_sql("items", [("id", "INTEGER"), ("name", "TEXT")], "postgres")
    assert sql == 'CREATE TABLE raw."items" ("id" BIGINT, "name" TEXT)'


def test_copy_counts_log_and_idempotency():
    with tempfile.TemporaryDirectory() as folder:
        src = os.path.join(folder, "source.db")
        make_source(src)
        dst = sqlite3.connect(":memory:")
        results = load(src, dst, "sqlite")
        assert {r["table"] for r in results} == {"items", "empty_table"}
        assert all(r["ok"] for r in results)
        assert dst.execute("SELECT COUNT(*) FROM items").fetchone()[0] == 3
        logged = dst.execute("SELECT source_file, source_sha256 FROM etl_load_log").fetchall()
        assert len(logged) == 2 and logged[0][0] == "source.db" and len(logged[0][1]) == 64
        load(src, dst, "sqlite")   # run again: data replaced, not doubled
        assert dst.execute("SELECT COUNT(*) FROM items").fetchone()[0] == 3
        dst.close()


def test_sqlite_internal_tables_are_not_copied():
    with tempfile.TemporaryDirectory() as folder:
        src = os.path.join(folder, "source.db")
        make_source(src)   # AUTOINCREMENT creates sqlite_sequence
        dst = sqlite3.connect(":memory:")
        assert "sqlite_sequence" not in {r["table"] for r in load(src, dst, "sqlite")}
        dst.close()
