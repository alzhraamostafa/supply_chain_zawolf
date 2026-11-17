"""Usage (inside Docker): python load_to_postgres.py /data/<file>.db
Connection settings come from the PGHOST, PGPORT, PGDATABASE, PGUSER, PGPASSWORD variables."""
import os
import sys

import psycopg

from loader import load


def main() -> int:
    src = sys.argv[1] if len(sys.argv) > 1 else "/data/logistic_in_cosmatic.db"
    with psycopg.connect(host=os.environ["PGHOST"], port=os.environ.get("PGPORT", "5432"),
                         dbname=os.environ["PGDATABASE"], user=os.environ["PGUSER"],
                         password=os.environ["PGPASSWORD"]) as con:
        results = load(src, con, "postgres")
    for r in results:
        print(f"{'OK ' if r['ok'] else 'BAD'} {r['table']}: {r['rows_source']} -> {r['rows_loaded']}")
    bad = [r for r in results if not r["ok"]]
    print(f"\n{len(results)} tables loaded, {len(bad)} with a row-count mismatch")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
