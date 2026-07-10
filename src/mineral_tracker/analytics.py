"""相場統計と割安検出。"""
from __future__ import annotations

import logging

import pandas as pd

from .models import Listing

logger = logging.getLogger(__name__)


def compute_unit_prices(listings: list[Listing]) -> None:
    for l in listings:
        if l.weight_g and l.weight_g > 0:
            l.unit_price_g = round(l.price_jpy / l.weight_g, 2)
        if l.size_mm_max and l.size_mm_max > 0:
            l.unit_price_mm = round(l.price_jpy / l.size_mm_max, 2)


def reference_stats(history: pd.DataFrame, min_samples: int) -> pd.DataFrame:
    """種別×ソース通貨圏ごとの基準相場(直近ウィンドウのg単価/mm単価の中央値)。

    履歴が薄い間は種別のみでグルーピング。"""
    if history.empty:
        return pd.DataFrame()
    df = history.copy()
    rows = []
    for species, g in df.groupby("species"):
        rec = {"species": species, "n": len(g)}
        for col, out in (("unit_price_g", "median_price_g"), ("unit_price_mm", "median_price_mm")):
            vals = pd.to_numeric(g[col], errors="coerce").dropna() if col in g else pd.Series(dtype=float)
            # 外れ値(上下5%)を除外
            if len(vals) >= min_samples:
                lo, hi = vals.quantile(0.05), vals.quantile(0.95)
                vals = vals[(vals >= lo) & (vals <= hi)]
                rec[out] = float(vals.median())
                rec[out + "_n"] = int(len(vals))
            else:
                rec[out] = None
                rec[out + "_n"] = int(len(vals))
        rows.append(rec)
    return pd.DataFrame(rows)


def detect_bargains(
    listings: list[Listing],
    history: pd.DataFrame,
    threshold: float = 0.6,
    min_samples: int = 8,
) -> list[Listing]:
    """基準相場に対して単価が threshold 未満の現役出品を割安候補としてマーク。"""
    refs = reference_stats(history, min_samples)
    if refs.empty:
        logger.info("履歴不足のため割安検出をスキップ")
        return []
    ref_map = refs.set_index("species").to_dict("index")
    bargains = []
    for l in listings:
        ref = ref_map.get(l.species)
        if not ref:
            continue
        ratio = None
        if l.unit_price_g and ref.get("median_price_g"):
            ratio = l.unit_price_g / ref["median_price_g"]
        elif l.unit_price_mm and ref.get("median_price_mm"):
            ratio = l.unit_price_mm / ref["median_price_mm"]
        if ratio is not None and 0 < ratio < threshold:
            l.is_bargain = True
            l.bargain_ratio = round(ratio, 3)
            bargains.append(l)
    bargains.sort(key=lambda x: x.bargain_ratio or 1.0)
    return bargains


def daily_summary(history: pd.DataFrame) -> pd.DataFrame:
    """種別×日付の中央値価格推移(レポートのグラフ用)。"""
    if history.empty:
        return pd.DataFrame()
    df = history.copy()
    df["price_jpy"] = pd.to_numeric(df["price_jpy"], errors="coerce")
    return (
        df.groupby(["species", "snapshot_date"])
        .agg(
            n=("listing_id", "count"),
            median_price=("price_jpy", "median"),
            median_unit_g=("unit_price_g", lambda s: pd.to_numeric(s, errors="coerce").median()),
        )
        .reset_index()
        .sort_values(["species", "snapshot_date"])
    )
