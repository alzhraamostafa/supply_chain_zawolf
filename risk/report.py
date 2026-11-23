"""Usage: python -m risk.report path/to/database.db"""
import sqlite3
import sys
from collections import Counter

from .adapter import assess_all, load_histories


def main() -> int:
    if len(sys.argv) < 2:
        sys.exit("Pass the .db path as an argument")
    con = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
    results = assess_all(con)
    counts = Counter(a.level for a in results)
    print("Levels:", ", ".join(f"{k} {counts[k]}" for k in ("critical", "high", "medium", "low", "unknown")))
    print("\nTop 10 (stock is unknown for every material, so levels use the supply fragility index):")
    for a in [x for x in results if x.level != "unknown"][:10]:
        print(f"  {a.level:8s} {a.material:32s} score {a.risk_score:.2f}  confidence {a.confidence:.2f}")
    unmatched = load_histories(con).unmatched_skus
    if unmatched:
        print(f"\n{len(unmatched)} RFQ SKUs match no BOM material or packaging item: {', '.join(unmatched)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())