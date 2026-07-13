"""コレクター基底クラス。"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from datetime import datetime, timezone, timedelta

from ..models import Listing
from ..normalize import classify_form, classify_premium, classify_species, extract_size

JST = timezone(timedelta(hours=9))
logger = logging.getLogger(__name__)


class BaseCollector(ABC):
    source_name: str = ""

    def __init__(self, source_cfg: dict, exchange_cfg: dict,
                 species_matcher: list[tuple[str, str]] | None = None):
        self.cfg = source_cfg
        self.exchange = exchange_cfg
        self.matcher = species_matcher or []

    @abstractmethod
    def search(self, keyword: str, species: str) -> list[Listing]:
        """1キーワード分の検索結果をListingとして返す。"""

    def browse(self) -> list[Listing]:
        """カテゴリを丸ごと巡回して収集(カテゴリ収集方式)。対応ソースで実装。"""
        raise NotImplementedError(f"{self.source_name} はカテゴリ収集に未対応")

    def collect(self, stones: list[dict]) -> list[Listing]:
        """browse設定(category/browse_keywords/sellers)があれば丸ごと巡回、
        無ければ従来のキーワード検索。"""
        if (self.cfg.get("category") or self.cfg.get("browse_keywords")
                or self.cfg.get("sellers") or self.cfg.get("sold_sellers")):
            excludes = self.global_excludes()
            items = self.browse()
            kept = [it for it in items if not self._is_excluded(it.title, excludes)]
            logger.info("%s: category browse -> %d items (除外 %d)",
                        self.source_name, len(kept), len(items) - len(kept))
            return kept
        results: list[Listing] = []
        for stone in stones:
            excludes = self.exclude_for(stone)
            for kw in self.keywords_for(stone):
                try:
                    items = self.search(kw, stone["species"])
                    kept = [it for it in items if not self._is_excluded(it.title, excludes)]
                    dropped = len(items) - len(kept)
                    logger.info(
                        "%s: '%s' -> %d items%s", self.source_name, kw, len(kept),
                        f" (除外 {dropped})" if dropped else "",
                    )
                    results.extend(kept)
                except Exception:
                    logger.exception("%s: keyword '%s' failed", self.source_name, kw)
        return results

    def keywords_for(self, stone: dict) -> list[str]:
        return stone.get("keywords_ja", [])

    def exclude_for(self, stone: dict) -> list[str]:
        """タイトルにこれらの語を含む出品を除外(アニメグッズ・アクセサリー等の混入対策)。"""
        return [w.lower() for w in stone.get("exclude", []) if w]

    def global_excludes(self) -> list[str]:
        """カテゴリ収集時にソース全体へ適用する除外語。"""
        return [w.lower() for w in self.cfg.get("exclude", []) if w]

    @staticmethod
    def _is_excluded(title: str, excludes: list[str]) -> bool:
        t = (title or "").lower()
        return any(w in t for w in excludes)

    @staticmethod
    def now_iso() -> str:
        return datetime.now(JST).isoformat(timespec="seconds")

    def enrich_size(self, listing: Listing) -> Listing:
        info = extract_size(listing.title)
        listing.size_mm_max = info["size_mm_max"]
        listing.volume_mm3 = info["volume_mm3"]
        listing.weight_g = info["weight_g"]
        listing.weight_ct = info["weight_ct"]
        listing.size_raw = info["size_raw"]
        listing.form = classify_form(listing.title)
        listing.premium_tag = classify_premium(listing.title)
        listing.premium = listing.premium_tag is not None
        # タイトルから種を判定。確信できた時のみ上書き(未分類は元のspeciesを維持)
        if self.matcher:
            sp = classify_species(listing.title, self.matcher)
            if sp != "other":
                listing.species = sp
        return listing
