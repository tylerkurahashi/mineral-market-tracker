"""Yahoo!フリマ(旧PayPayフリマ)コレクター。

フリマは固定価格のため、相場(基準価格)の根拠に使える(オークションと違い価格が確定)。
検索ページのサーバー埋め込みJSON(__NEXT_DATA__)から商品を取得する。
- 公式APIではないため、ページ構造の変更で動かなくなる可能性がある(自己責任で運用)
- request_interval_sec を必ず空けて負荷をかけない
"""
from __future__ import annotations

import json
import logging
import re
import time
from datetime import date
from urllib.parse import quote

import requests

from ..models import Listing
from .base import BaseCollector

logger = logging.getLogger(__name__)

SEARCH_URL = "https://paypayfleamarket.yahoo.co.jp/search/{kw}"
ITEM_URL = "https://paypayfleamarket.yahoo.co.jp/item/{id}"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
_RE_NEXT = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)


class YahooFleaCollector(BaseCollector):
    source_name = "yahoo_flea"

    def search(self, keyword: str, species: str) -> list[Listing]:
        url = SEARCH_URL.format(kw=quote(keyword))
        interval = self.cfg.get("request_interval_sec", 3.0)
        html = None
        for attempt in range(3):  # レート制限(429/403)対策に軽くリトライ
            r = requests.get(url, headers={"User-Agent": UA}, timeout=30)
            if r.status_code == 200:
                html = r.text
                time.sleep(interval)
                break
            if r.status_code in (429, 403, 503):
                wait = interval * (attempt + 2)
                logger.warning("yahoo_flea: %s → %ss待って再試行 (%s)", r.status_code, wait, keyword)
                time.sleep(wait)
                continue
            r.raise_for_status()
        if html is None:
            logger.warning("yahoo_flea: リトライ上限。スキップ (%s)", keyword)
            return []
        return self._parse(html, species)

    def browse(self) -> list[Listing]:
        """広域キーワード(config.browse_keywords)でフリマを収集。種はタイトルから分類。"""
        out: list[Listing] = []
        for kw in self.cfg.get("browse_keywords", []):
            try:
                out.extend(self.search(kw, "other"))
            except Exception:
                logger.exception("yahoo_flea: browse keyword '%s' failed", kw)
        return out

    def _parse(self, html: str, species: str = "other") -> list[Listing]:
        m = _RE_NEXT.search(html)
        if not m:
            logger.warning("yahoo_flea: __NEXT_DATA__ が見つからない(構造変更の可能性)")
            return []
        try:
            data = json.loads(m.group(1))
            items = data["props"]["initialState"]["searchState"]["search"]["result"]["items"]
        except (json.JSONDecodeError, KeyError, TypeError):
            logger.warning("yahoo_flea: JSON構造が想定と異なる(構造変更の可能性)")
            return []

        today = date.today().isoformat()
        limit = self.cfg.get("limit_per_keyword", 50)
        out: list[Listing] = []
        for it in items[:limit]:
            item_id = it.get("id")
            price = it.get("price")
            title = it.get("title") or ""
            if not item_id or not price:
                continue
            # 売り切れは相場の実績値として有用だが、既定は販売中(OPEN)のみ収集
            status = (it.get("itemStatus") or "").upper()
            if not self.cfg.get("include_sold", False) and status not in ("", "OPEN"):
                continue
            img = it.get("thumbnailImageUrl")
            listing = Listing(
                listing_id=f"yahoo_flea:{item_id}",
                source=self.source_name,
                species=species,
                title=title,
                url=ITEM_URL.format(id=item_id),
                price_original=float(price),
                currency="JPY",
                price_jpy=float(price),
                snapshot_date=today,
                collected_at=self.now_iso(),
                listing_type="fixed",
                image_urls=[img] if img else [],
            )
            out.append(self.enrich_size(listing))
        return out
