"""Claude vision による画像品質評価。

コスト管理:
- sources.yaml の quality.max_listings_per_day で日次上限
- only_bargain_candidates=true なら割安候補のみ評価
"""
from __future__ import annotations

import base64
import json
import logging

import requests

from .config import env
from .models import Listing

logger = logging.getLogger(__name__)

PROMPT = """あなたは鉱物標本・ルースの鑑定補助AIです。画像の石について以下をJSONのみで返してください。
{
  "transparency": 0-10の数値(透明度。不透明鉱物は結晶面の質で代替),
  "color": 0-10の数値(色の鮮やかさ・濃さ・均一性),
  "condition": 0-10の数値(傷・欠け・母岩ダメージの少なさ),
  "overall": 0-10の数値(標本/ルースとしての総合評価),
  "notes": "50字以内の所見(日本語)"
}
画像が不鮮明・石以外の場合は overall を 0 とし notes に理由を書くこと。JSON以外を出力しないこと。"""

MEDIA_TYPES = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
               "gif": "image/gif", "webp": "image/webp"}


def _fetch_image_b64(url: str) -> tuple[str, str] | None:
    try:
        r = requests.get(url, timeout=20)
        r.raise_for_status()
        ext = url.split("?")[0].rsplit(".", 1)[-1].lower()
        media = MEDIA_TYPES.get(ext, r.headers.get("Content-Type", "image/jpeg").split(";")[0])
        if len(r.content) > 4_500_000:  # APIの5MB制限を回避
            return None
        return base64.b64encode(r.content).decode(), media
    except Exception:
        logger.warning("image fetch failed: %s", url)
        return None


def evaluate_listing(listing: Listing, model: str) -> Listing:
    """出品の先頭画像を評価してスコアを埋める。失敗時はNoneのまま。"""
    import anthropic

    if not listing.image_urls:
        return listing
    fetched = _fetch_image_b64(listing.image_urls[0])
    if not fetched:
        return listing
    b64, media = fetched

    client = anthropic.Anthropic(api_key=env("ANTHROPIC_API_KEY"))
    try:
        msg = client.messages.create(
            model=model,
            max_tokens=300,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image",
                     "source": {"type": "base64", "media_type": media, "data": b64}},
                    {"type": "text", "text": PROMPT},
                ],
            }],
        )
        text = msg.content[0].text.strip()
        if text.startswith("```"):
            text = text.strip("`").removeprefix("json").strip()
        data = json.loads(text)
        listing.q_transparency = float(data.get("transparency", 0))
        listing.q_color = float(data.get("color", 0))
        listing.q_condition = float(data.get("condition", 0))
        listing.q_overall = float(data.get("overall", 0))
        listing.q_notes = str(data.get("notes", ""))[:100]
    except Exception:
        logger.exception("quality eval failed: %s", listing.listing_id)
    return listing


def evaluate_batch(listings: list[Listing], quality_cfg: dict) -> int:
    """設定に従い対象を絞って評価。評価した件数を返す。"""
    if not env("ANTHROPIC_API_KEY"):
        logger.warning("ANTHROPIC_API_KEY 未設定のため品質評価をスキップ")
        return 0
    model = quality_cfg.get("model", "claude-haiku-4-5-20251001")
    limit = quality_cfg.get("max_listings_per_day", 40)
    targets = [l for l in listings if l.image_urls and l.q_overall is None]
    if quality_cfg.get("only_bargain_candidates", True):
        candidates = [l for l in targets if l.is_bargain]
        if candidates:
            targets = candidates
    count = 0
    for l in targets[:limit]:
        evaluate_listing(l, model)
        count += 1
    return count
