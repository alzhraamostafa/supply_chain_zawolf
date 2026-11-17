"""Usage: python -m data_quality.report path/to/database.db"""
import sqlite3
import sys

from .checks import run_all


def main() -> int:
    if len(sys.argv) < 2:
        sys.exit("Pass the .db path as an argument")
    con = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
    failed = 0
    for name, problems in run_all(con).items():
        if problems:
            failed += 1
            print(f"FAIL {name}")
            for p in problems[:5]:
                print(f"     - {p}")
            if len(problems) > 5:
                print(f"     ... and {len(problems) - 5} more")
        else:
            print(f"PASS {name}")
    print(f"\n{failed} of {len(run_all(con))} checks failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
