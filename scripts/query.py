#!/usr/bin/env python3
"""保存済みデータへのSQL照会。例:
python scripts/query.py "SELECT species, count(*) n, median(price_jpy) FROM listings GROUP BY species ORDER BY n DESC"
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from mineral_tracker import storage

if __name__ == "__main__":
    sql = sys.argv[1] if len(sys.argv) > 1 else "SELECT species, count(*) AS n FROM listings GROUP BY species"
    print(storage.query(sql).to_string(index=False))
