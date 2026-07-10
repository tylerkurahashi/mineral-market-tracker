"""データモデル定義。"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import date, datetime
from typing import Optional


@dataclass
class Listing:
    """1出品のスナップショット。日次で同一出品が再収集されることを許容する
    (listing_id + snapshot_date が実質キー)。"""

    listing_id: str            # ソース内で一意なID (source prefix付き, 例 "ebay:v1|...")
    source: str                # ebay / yahoo_auctions / shop:<name>
    species: str               # 正規化キー (config/stones.yaml)
    title: str
    url: str
    price_original: float      # 元通貨での価格
    currency: str              # JPY / USD ...
    price_jpy: float           # JPY換算価格
    snapshot_date: str         # YYYY-MM-DD
    collected_at: str          # ISO8601
    listing_type: str = "fixed"   # fixed / auction
    status: str = "active"        # active / sold / ended
    image_urls: list[str] = field(default_factory=list)
    # --- 正規化されたサイズ・重量 (タイトル/説明から抽出, 不明はNone) ---
    weight_g: Optional[float] = None
    weight_ct: Optional[float] = None
    size_mm_max: Optional[float] = None   # 最長辺
    size_raw: Optional[str] = None        # 抽出元の生文字列
    # --- 品質評価 (Claude vision, 未評価はNone) ---
    q_transparency: Optional[float] = None
    q_color: Optional[float] = None
    q_condition: Optional[float] = None   # 傷・欠けの少なさ
    q_overall: Optional[float] = None
    q_notes: Optional[str] = None
    # --- 分析結果 ---
    unit_price_g: Optional[float] = None      # price_jpy / weight_g
    unit_price_mm: Optional[float] = None     # price_jpy / size_mm_max
    is_bargain: bool = False
    bargain_ratio: Optional[float] = None     # 単価 / 基準相場中央値

    def to_dict(self) -> dict:
        d = asdict(self)
        d["image_urls"] = list(self.image_urls or [])
        return d
