"""ヤフオク 即決限定セラー コレクター。

エヌズミネラルのように基本的に即決(固定価格)のみで出品する優良セラーを巡回する。
即決＝価格が確定しているため、相場(baseline)の良質な根拠になる。
セラーページは Next.js の __NEXT_DATA__ に商品が入っているのでそこから取得する。
"""
from __future__ import annotations

import json
import logging
import re
import time
from datetime import date

import requests
from bs4 import BeautifulSoup

from ..models import Listing
from ..normalize import classify_form, extract_size
from .base import BaseCollector

logger = logging.getLogger(__name__)

SELLER_URL = "https://auctions.yahoo.co.jp/seller/{sid}?n={n}&b={b}"
ITEM_URL = "https://auctions.yahoo.co.jp/jp/auction/{aid}"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
_RE_NEXT = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)


class YahooSellerCollector(BaseCollector):
    source_name = "yahoo_seller"

    def search(self, keyword: str, species: str) -> list[Listing]:  # 未使用(browse専用)
        return []

    def browse(self) -> list[Listing]:
        n = min(self.cfg.get("limit_per_keyword", 50), 100)
        max_items = self.cfg.get("max_items", 200)
        interval = self.cfg.get("request_interval_sec", 3.0)
        out: list[Listing] = []
        for sid in self.cfg.get("sellers", []):
            got, b = 0, 1
            while got < max_items:
                url = SELLER_URL.format(sid=sid, n=n, b=b)
                r = requests.get(url, headers={"User-Agent": UA}, timeout=30)
                r.raise_for_status()
                time.sleep(interval)
                items = self._parse(r.text)
                if not items:
                    break
                out.extend(items)
                got += len(items)
                b += n
        # 説明文からサイズ/重量を補完(このセラーはタイトルに寸法が無い)
        if self.cfg.get("fetch_detail"):
            cap = self.cfg.get("detail_max", 200)
            for l in out[:cap]:
                self._enrich_from_detail(l, interval)
        return out

    def _enrich_from_detail(self, listing: Listing, interval: float) -> None:
        """商品詳細ページの説明文からサイズ/重量を抽出して補完する。"""
        aid = listing.listing_id.split(":")[-1]
        try:
            r = requests.get(ITEM_URL.format(aid=aid), headers={"User-Agent": UA}, timeout=30)
            r.raise_for_status()
            time.sleep(interval)
            m = _RE_NEXT.search(r.text)
            if not m:
                return
            desc_html = self._find_description(json.loads(m.group(1)))
            if not desc_html:
                return
            desc = BeautifulSoup(desc_html, "lxml").get_text(" ", strip=True)
            text = f"{listing.title} {desc}"
            info = extract_size(text)
            for k in ("size_mm_max", "volume_mm3", "weight_g", "weight_ct", "size_raw"):
                if info[k] is not None:
                    setattr(listing, k, info[k])
            listing.form = classify_form(text)  # 説明文も加味して形態判定
        except Exception:
            logger.warning("yahoo_seller: 詳細取得失敗 %s", aid)

    @staticmethod
    def _find_description(dj: dict) -> str | None:
        node = dj.get("props", {})
        for path in (("pageProps", "initialState"), ("initialState",)):
            cur = node
            for key in path:
                cur = cur.get(key, {}) if isinstance(cur, dict) else {}
            desc = (((cur.get("item") or {}).get("detail") or {}).get("item") or {}).get("descriptionHtml")
            if desc:
                return desc
        return None

    def _parse(self, html: str) -> list[Listing]:
        m = _RE_NEXT.search(html)
        if not m:
            logger.warning("yahoo_seller: __NEXT_DATA__ が見つからない(構造変更の可能性)")
            return []
        try:
            data = json.loads(m.group(1))
            items = data["props"]["pageProps"]["initialState"]["search"]["items"]["listing"]["items"]
        except (json.JSONDecodeError, KeyError, TypeError):
            logger.warning("yahoo_seller: JSON構造が想定と異なる(構造変更の可能性)")
            return []

        today = date.today().isoformat()
        out: list[Listing] = []
        for it in items:
            aid = it.get("auctionId")
            # 即決価格を優先(無ければ現在価格)。即決セラー前提なので固定価格扱い。
            price = it.get("buyNowPrice") or it.get("price")
            if not aid or not price:
                continue
            img = it.get("imageUrl")
            listing = Listing(
                listing_id=f"yahoo:{aid}",
                source=self.source_name,
                species="other",  # タイトルから分類(enrich_size)
                title=it.get("title") or "",
                url=ITEM_URL.format(aid=aid),
                price_original=float(price),
                currency="JPY",
                price_jpy=float(price),
                snapshot_date=today,
                collected_at=self.now_iso(),
                listing_type="fixed",
                bids=it.get("bidCount"),
                image_urls=[img] if img else [],
            )
            out.append(self.enrich_size(listing))
        return out
