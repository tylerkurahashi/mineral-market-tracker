"""eBay Browse API コレクター(公式API)。

事前に https://developer.ebay.com/ でアプリ登録し、
.env に EBAY_CLIENT_ID / EBAY_CLIENT_SECRET を設定すること。
Client Credentials フローで application token を取得して検索する。
"""
from __future__ import annotations

import base64
from datetime import date

import requests

from ..config import env
from ..models import Listing
from ..normalize import to_jpy
from .base import BaseCollector

TOKEN_URL = "https://api.ebay.com/identity/v1/oauth2/token"
SEARCH_URL = "https://api.ebay.com/buy/browse/v1/item_summary/search"
SCOPE = "https://api.ebay.com/oauth/api_scope"


class EbayCollector(BaseCollector):
    source_name = "ebay"

    def __init__(self, source_cfg: dict, exchange_cfg: dict):
        super().__init__(source_cfg, exchange_cfg)
        self._token: str | None = None

    def keywords_for(self, stone: dict) -> list[str]:
        return stone.get("keywords_en", [])

    def _get_token(self) -> str:
        if self._token:
            return self._token
        cid, secret = env("EBAY_CLIENT_ID"), env("EBAY_CLIENT_SECRET")
        if not cid or not secret:
            raise RuntimeError("EBAY_CLIENT_ID / EBAY_CLIENT_SECRET が未設定です")
        auth = base64.b64encode(f"{cid}:{secret}".encode()).decode()
        r = requests.post(
            TOKEN_URL,
            headers={"Authorization": f"Basic {auth}",
                     "Content-Type": "application/x-www-form-urlencoded"},
            data={"grant_type": "client_credentials", "scope": SCOPE},
            timeout=30,
        )
        r.raise_for_status()
        self._token = r.json()["access_token"]
        return self._token

    def search(self, keyword: str, species: str) -> list[Listing]:
        params = {
            "q": keyword,
            "limit": self.cfg.get("limit_per_keyword", 50),
        }
        if self.cfg.get("category_ids"):
            params["category_ids"] = str(self.cfg["category_ids"])
        r = requests.get(
            SEARCH_URL,
            params=params,
            headers={
                "Authorization": f"Bearer {self._get_token()}",
                "X-EBAY-C-MARKETPLACE-ID": self.cfg.get("marketplace", "EBAY_US"),
            },
            timeout=30,
        )
        r.raise_for_status()
        items = r.json().get("itemSummaries", []) or []
        today = date.today().isoformat()
        fallback = self.exchange.get("fallback_usd_jpy", 155.0)
        out = []
        for it in items:
            price = it.get("price") or {}
            if not price.get("value"):
                continue
            value = float(price["value"])
            currency = price.get("currency", "USD")
            images = []
            if it.get("image", {}).get("imageUrl"):
                images.append(it["image"]["imageUrl"])
            for extra in it.get("additionalImages", []) or []:
                if extra.get("imageUrl"):
                    images.append(extra["imageUrl"])
            buying = it.get("buyingOptions", []) or []
            listing = Listing(
                listing_id=f"ebay:{it['itemId']}",
                source=self.source_name,
                species=species,
                title=it.get("title", ""),
                url=it.get("itemWebUrl", ""),
                price_original=value,
                currency=currency,
                price_jpy=to_jpy(value, currency, fallback),
                snapshot_date=today,
                collected_at=self.now_iso(),
                listing_type="auction" if "AUCTION" in buying else "fixed",
                image_urls=images[:5],
            )
            out.append(self.enrich_size(listing))
        return out
