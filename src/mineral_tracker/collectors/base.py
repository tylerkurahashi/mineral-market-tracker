"""コレクター基底クラス。"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from datetime import datetime, timezone, timedelta

from ..models import Listing
from ..normalize import extract_size

JST = timezone(timedelta(hours=9))
logger = logging.getLogger(__name__)


class BaseCollector(ABC):
    source_name: str = ""

    def __init__(self, source_cfg: dict, exchange_cfg: dict):
        self.cfg = source_cfg
        self.exchange = exchange_cfg

    @abstractmethod
    def search(self, keyword: str, species: str) -> list[Listing]:
        """1キーワード分の検索結果をListingとして返す。"""

    def collect(self, stones: list[dict]) -> list[Listing]:
        """全鉱物分を収集。キーワードは言語別フィールドを使用。"""
        results: list[Listing] = []
        for stone in stones:
            for kw in self.keywords_for(stone):
                try:
                    items = self.search(kw, stone["species"])
                    logger.info("%s: '%s' -> %d items", self.source_name, kw, len(items))
                    results.extend(items)
                except Exception:
                    logger.exception("%s: keyword '%s' failed", self.source_name, kw)
        return results

    def keywords_for(self, stone: dict) -> list[str]:
        return stone.get("keywords_ja", [])

    @staticmethod
    def now_iso() -> str:
        return datetime.now(JST).isoformat(timespec="seconds")

    @staticmethod
    def enrich_size(listing: Listing) -> Listing:
        info = extract_size(listing.title)
        listing.size_mm_max = info["size_mm_max"]
        listing.weight_g = info["weight_g"]
        listing.weight_ct = info["weight_ct"]
        listing.size_raw = info["size_raw"]
        return listing
