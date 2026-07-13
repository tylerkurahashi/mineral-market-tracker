"""Yahoo!フリマ SOLD(売却済み)コレクター。

出品者ページ /user/{id} の __NEXT_DATA__ から売却済み商品を取得する。
売却価格(price)と売却日(endTime)が取れるので、実際に成立した取引＝実績相場になる。
希望価格(asking)と違い売れ残りバイアスが無く、相場の根拠として最も信頼できる。

対象は「販売実績があり産地表記のある標本商」に絞る(config.sold_sellers)。
選別は scripts/vet_seller.py で SOLD件数・産地表記率をチェックしてから登録する。
"""
from __future__ import annotations

import json
import logging
import re
import time
from urllib.parse import quote

import requests

from ..models import Listing
from .base import BaseCollector

logger = logging.getLogger(__name__)

USER_URL = "https://paypayfleamarket.yahoo.co.jp/user/{sid}"
ITEM_URL = "https://paypayfleamarket.yahoo.co.jp/item/{id}"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
_RE_NEXT = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)


def parse_user_items(html: str) -> list[dict]:
    """出品者ページの __NEXT_DATA__ から商品配列を取り出す。失敗時は空。"""
    m = _RE_NEXT.search(html)
    if not m:
        return []
    try:
        data = json.loads(m.group(1))
        return data["props"]["initialState"]["searchState"]["search"]["result"]["items"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return []


class YahooFleaSoldCollector(BaseCollector):
    source_name = "yahoo_flea_sold"

    def search(self, keyword: str, species: str) -> list[Listing]:  # 未使用(browse専用)
        return []

    def browse(self) -> list[Listing]:
        """config.sold_sellers の出品者ページから SOLD 商品を収集。"""
        interval = self.cfg.get("request_interval_sec", 6.0)
        out: list[Listing] = []
        for sid in self.cfg.get("sold_sellers", []):
            try:
                r = requests.get(USER_URL.format(sid=sid), headers={"User-Agent": UA}, timeout=30)
                if r.status_code != 200:
                    logger.warning("yahoo_flea_sold: %s -> %s (スキップ)", sid, r.status_code)
                    continue
                time.sleep(interval)
                items = [it for it in parse_user_items(r.text) if it.get("itemStatus") == "SOLD"]
                logger.info("yahoo_flea_sold: %s -> SOLD %d件", sid, len(items))
                out.extend(self._to_listing(it) for it in items if self._to_listing(it))
            except Exception:
                logger.exception("yahoo_flea_sold: %s 取得失敗", sid)
        return [l for l in out if l]

    def _to_listing(self, it: dict) -> Listing | None:
        item_id, price = it.get("id"), it.get("price")
        end = it.get("endTime")  # SOLD品の endTime = 売却日時
        if not item_id or not price or not end:
            return None
        listing = Listing(
            listing_id=f"yahoo_flea:{item_id}",
            source=self.source_name,
            species="other",  # タイトルから分類(enrich_size)
            title=it.get("title") or "",
            url=ITEM_URL.format(id=item_id),
            price_original=float(price),
            currency="JPY",
            price_jpy=float(price),
            snapshot_date=None,  # collect側で本日を入れる
            collected_at=self.now_iso(),
            listing_type="fixed",
            status="sold",
            sold_date=str(end)[:10],
            image_urls=[it["thumbnailImageUrl"]] if it.get("thumbnailImageUrl") else [],
        )
        return self.enrich_size(listing)
