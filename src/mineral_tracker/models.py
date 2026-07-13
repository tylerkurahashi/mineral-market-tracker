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
    sold_date: Optional[str] = None       # 売却日 YYYY-MM-DD (status=sold のみ) = 実績相場の日付
    bids: Optional[int] = None            # 入札数 (オークションのみ)
    ends_in_hours: Optional[float] = None # 収集時点での残り時間(h)。オークションのみ
    image_urls: list[str] = field(default_factory=list)
    form: str = "unknown"          # loose(カット石/ルース) / rough(原石) / unknown
    premium: bool = False          # 価格が跳ねる特殊要素(バイカラー/パライバ/共生標本等)
    premium_tag: Optional[str] = None  # 該当した要素名(表示用)
    # --- 正規化されたサイズ・重量 (タイトル/説明から抽出, 不明はNone) ---
    weight_g: Optional[float] = None
    weight_ct: Optional[float] = None
    size_mm_max: Optional[float] = None   # 最長辺
    volume_mm3: Optional[float] = None    # 直方体近似の体積 (3辺揃う時のみ)
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
    unit_price_vol: Optional[float] = None    # price_jpy / volume_mm3 (円/mm³)
    is_bargain: bool = False
    bargain_ratio: Optional[float] = None     # 単価 / 基準相場中央値

    def to_dict(self) -> dict:
        d = asdict(self)
        d["image_urls"] = list(self.image_urls or [])
        return d
