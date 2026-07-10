"""Parquetストレージ層。data/listings/date=YYYY-MM-DD/ に日次パーティション保存。"""
from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd

from .config import DATA_DIR
from .models import Listing

LISTINGS_DIR = DATA_DIR / "listings"


def save_listings(listings: list[Listing], snapshot_date: str) -> Path:
    """日次スナップショットをParquetに保存(同日分は上書き)。"""
    if not listings:
        raise ValueError("no listings to save")
    part = LISTINGS_DIR / f"date={snapshot_date}"
    part.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame([l.to_dict() for l in listings])
    # 同一出品が複数キーワードでヒットした場合の重複排除
    df = df.drop_duplicates(subset=["listing_id"], keep="first")
    path = part / "listings.parquet"
    df.to_parquet(path, index=False)
    return path


def load_all(window_days: int | None = None) -> pd.DataFrame:
    """保存済み全データ(または直近N日)をDataFrameで返す。"""
    if not LISTINGS_DIR.exists():
        return pd.DataFrame()
    con = duckdb.connect()
    glob = str(LISTINGS_DIR / "date=*" / "*.parquet")
    try:
        q = f"SELECT * FROM read_parquet('{glob}', union_by_name=true)"
        if window_days:
            q += f" WHERE snapshot_date >= strftime(current_date - INTERVAL {int(window_days)} DAY, '%Y-%m-%d')"
        return con.execute(q).fetchdf()
    except duckdb.IOException:
        return pd.DataFrame()
    finally:
        con.close()


def query(sql: str) -> pd.DataFrame:
    """listings ビューに対して任意SQLを実行。"""
    con = duckdb.connect()
    glob = str(LISTINGS_DIR / "date=*" / "*.parquet")
    con.execute(
        f"CREATE VIEW listings AS SELECT * FROM read_parquet('{glob}', union_by_name=true)"
    )
    try:
        return con.execute(sql).fetchdf()
    finally:
        con.close()
