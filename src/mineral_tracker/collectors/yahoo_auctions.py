"""ヤフオク検索コレクター。

公式検索APIは提供されていないため、公開検索ページを低頻度で取得する。
- request_interval_sec を必ず空けて負荷をかけない
- ページ構造・規約の変更で動かなくなる可能性がある(自己責任で運用)
"""
from __future__ import annotations

import time
from datetime import date
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup

from ..models import Listing
from ..normalize import parse_time_left_hours
from .base import BaseCollector

SEARCH_URL = "https://auctions.yahoo.co.jp/search/search?p={kw}&n={n}"
CATEGORY_URL = "https://auctions.yahoo.co.jp/search/search?auccat={cat}&n={n}&b={b}"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"


class YahooAuctionsCollector(BaseCollector):
    source_name = "yahoo_auctions"

    def search(self, keyword: str, species: str) -> list[Listing]:
        n = min(self.cfg.get("limit_per_keyword", 50), 100)
        url = SEARCH_URL.format(kw=quote(keyword), n=n)
        r = requests.get(url, headers={"User-Agent": UA}, timeout=30)
        r.raise_for_status()
        time.sleep(self.cfg.get("request_interval_sec", 3.0))
        return self._parse(r.text, species)

    def browse(self) -> list[Listing]:
        """鉱物カテゴリ(config.category)を丸ごとページング取得。種はタイトルから分類。"""
        cats = self.cfg["category"]
        cats = cats if isinstance(cats, list) else [cats]
        n = min(self.cfg.get("limit_per_keyword", 50), 100)
        max_items = self.cfg.get("max_items", 300)
        interval = self.cfg.get("request_interval_sec", 3.0)
        out: list[Listing] = []
        for cat in cats:
            got, b = 0, 1
            while got < max_items:
                url = CATEGORY_URL.format(cat=cat, n=n, b=b)
                r = requests.get(url, headers={"User-Agent": UA}, timeout=30)
                r.raise_for_status()
                time.sleep(interval)
                items = self._parse(r.text, "other")
                if not items:
                    break
                out.extend(items)
                got += len(items)
                b += n
        return out

    def _parse(self, html: str, species: str = "other") -> list[Listing]:
        soup = BeautifulSoup(html, "lxml")
        today = date.today().isoformat()
        out: list[Listing] = []
        for li in soup.select("li.Product"):
            a = li.select_one("a.Product__titleLink")
            price_el = li.select_one(".Product__priceValue")
            if not a or not price_el:
                continue
            url = a.get("href", "")
            title = a.get_text(strip=True)
            price_txt = price_el.get_text(strip=True).replace(",", "").replace("円", "")
            try:
                price = float(price_txt)
            except ValueError:
                continue
            auction_id = url.rstrip("/").split("/")[-1].split("?")[0]
            img = li.select_one("img")
            images = [img["src"]] if img and img.get("src", "").startswith("http") else []
            # 入札数・残り時間 (ヤフオクは全件オークション形式)
            bid_el = li.select_one(".Product__bid")
            bids = None
            if bid_el:
                bt = bid_el.get_text(strip=True)
                bids = int(bt) if bt.isdigit() else None
            time_el = li.select_one(".Product__time")
            ends_in = parse_time_left_hours(time_el.get_text(strip=True)) if time_el else None
            listing = Listing(
                listing_id=f"yahoo:{auction_id}",
                source=self.source_name,
                species=species,
                title=title,
                url=url,
                price_original=price,
                currency="JPY",
                price_jpy=price,
                snapshot_date=today,
                collected_at=self.now_iso(),
                listing_type="auction",
                bids=bids,
                ends_in_hours=ends_in,
                image_urls=images,
            )
            out.append(self.enrich_size(listing))
        return out
