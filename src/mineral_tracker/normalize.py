"""タイトル・説明文からサイズ/重量を抽出し、通貨をJPYへ換算する。"""
from __future__ import annotations

import re
from functools import lru_cache

import requests

# 例: "45mm", "4.5cm", "45×30×20mm", "12.3g", "5.2ct", "5.2カラット", "12.3グラム"
_RE_MM = re.compile(r"(\d+(?:\.\d+)?)\s*(?:mm|ミリ|㎜)", re.I)
_RE_CM = re.compile(r"(\d+(?:\.\d+)?)\s*(?:cm|センチ|㎝)", re.I)
_RE_DIMS = re.compile(
    r"(\d+(?:\.\d+)?)\s*[x×*]\s*(\d+(?:\.\d+)?)(?:\s*[x×*]\s*(\d+(?:\.\d+)?))?\s*(mm|cm|㎜|㎝)?",
    re.I,
)
_RE_G = re.compile(r"(\d+(?:\.\d+)?)\s*(?:g|ｇ|グラム)(?![a-z])", re.I)
_RE_KG = re.compile(r"(\d+(?:\.\d+)?)\s*(?:kg|キロ)", re.I)
_RE_CT = re.compile(r"(\d+(?:\.\d+)?)\s*(?:ct|カラット|карат)", re.I)


def extract_size(text: str) -> dict:
    """テキストから size_mm_max / weight_g / weight_ct を抽出。"""
    out: dict = {"size_mm_max": None, "weight_g": None, "weight_ct": None, "size_raw": None}
    if not text:
        return out
    raws = []

    m = _RE_DIMS.search(text)
    if m:
        unit = (m.group(4) or "mm").lower()
        dims = [float(x) for x in m.groups()[:3] if x]
        factor = 10.0 if unit in ("cm", "㎝") else 1.0
        out["size_mm_max"] = max(dims) * factor
        raws.append(m.group(0))
    else:
        m = _RE_MM.search(text)
        if m:
            out["size_mm_max"] = float(m.group(1))
            raws.append(m.group(0))
        else:
            m = _RE_CM.search(text)
            if m:
                out["size_mm_max"] = float(m.group(1)) * 10.0
                raws.append(m.group(0))

    m = _RE_KG.search(text)
    if m:
        out["weight_g"] = float(m.group(1)) * 1000.0
        raws.append(m.group(0))
    else:
        m = _RE_G.search(text)
        if m:
            out["weight_g"] = float(m.group(1))
            raws.append(m.group(0))

    m = _RE_CT.search(text)
    if m:
        out["weight_ct"] = float(m.group(1))
        if out["weight_g"] is None:
            out["weight_g"] = out["weight_ct"] * 0.2  # 1ct = 0.2g
        raws.append(m.group(0))

    # 異常値ガード
    if out["size_mm_max"] and not (1 <= out["size_mm_max"] <= 2000):
        out["size_mm_max"] = None
    if out["weight_g"] and not (0.01 <= out["weight_g"] <= 100_000):
        out["weight_g"] = None

    out["size_raw"] = " / ".join(raws) if raws else None
    return out


@lru_cache(maxsize=8)
def get_rate_to_jpy(currency: str, fallback_usd_jpy: float = 155.0) -> float:
    """為替レート取得(frankfurter.app, ECB公表値)。失敗時フォールバック。"""
    currency = currency.upper()
    if currency == "JPY":
        return 1.0
    try:
        r = requests.get(
            f"https://api.frankfurter.app/latest?from={currency}&to=JPY", timeout=10
        )
        r.raise_for_status()
        return float(r.json()["rates"]["JPY"])
    except Exception:
        if currency == "USD":
            return fallback_usd_jpy
        raise


def to_jpy(price: float, currency: str, fallback_usd_jpy: float = 155.0) -> float:
    return round(price * get_rate_to_jpy(currency, fallback_usd_jpy), 0)
