"""タイトル・説明文からサイズ/重量を抽出し、通貨をJPYへ換算する。"""
from __future__ import annotations

import re
import unicodedata
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

# --- 出品形態(ルース/原石)の判定用 ---
_RE_LOOSE = re.compile(r"ルース|裸石|jewel(?:ry|s)?|loose|ファセット|カボション|cabochon", re.I)
_RE_ROUGH = re.compile(
    r"原石|クラスター|標本|母岩|結晶|ラフ|さざれ|rough|specimen|cluster|slab|geode|晶洞",
    re.I,
)


# 価格が大きく跳ねる特殊要素。標準の相場から切り離して別枠で扱う。
# (キーワード, 表示タグ) の順。先にマッチしたものを採用。
_PREMIUM_TAGS = [
    ("パライバ", "パライバ"), ("paraiba", "パライバ"),
    ("バイカラー", "バイカラー"), ("トリカラー", "バイカラー"), ("bicolor", "バイカラー"),
    ("スイカトルマリン", "スイカ"), ("ウォーターメロン", "スイカ"), ("watermelon", "スイカ"),
    ("共生", "共生標本"), ("共生標本", "共生標本"),
    ("サンタマリア", "サンタマリア"), ("santa maria", "サンタマリア"),
    ("パパラチア", "パパラチア"), ("padparadscha", "パパラチア"),
    ("スタービアリング", "スター"), ("スター効果", "スター"), ("アステリズム", "スター"),
    ("キャッツアイ", "キャッツアイ"),
]


def classify_premium(text: str) -> str | None:
    """タイトルに価格急騰要素があればその表示タグを返す。無ければNone。"""
    if not text:
        return None
    low = text.lower()
    for kw, tag in _PREMIUM_TAGS:
        if kw in text or kw in low:
            return tag
    return None


_VU_COMBOS = [("ヴァ", "バ"), ("ヴィ", "ビ"), ("ヴェ", "ベ"), ("ヴォ", "ボ"),
              ("ヴュ", "ビュ"), ("ヴ", "ブ")]
_KANA_STRIP = re.compile(r"[ー〜～・－\-‐\s]")


def normalize_kana(text: str) -> str:
    """表記揺らぎ吸収のための正規化: NFKC・小文字化・長音符/中黒/空白除去・ヴ→バ行。

    例: 'ヴィリオーマイト' → 'ビリオマイト'、'カイヤ ナイト' → 'カイヤナイト'。
    別転写(マイト vs 石)までは吸収できない→そこはエイリアス辞書(層②)で対応。"""
    if not text:
        return ""
    t = unicodedata.normalize("NFKC", text).lower()
    for a, b in _VU_COMBOS:
        t = t.replace(a, b)
    return _KANA_STRIP.sub("", t)


def classify_species(title: str, matcher: list[tuple[str, str]]) -> str:
    """タイトルから鉱物種を判定。matcher は (正規化済み別名, species) を長い順に並べたもの。

    最初に部分一致した別名の species を返す。該当なしは 'other'。"""
    norm = normalize_kana(title)
    if not norm:
        return "other"
    for alias, species in matcher:
        if alias and alias in norm:
            return species
    return "other"


_RE_TIME_LEFT = re.compile(r"(\d+(?:\.\d+)?)\s*(日|時間|分|秒)")


def parse_time_left_hours(text: str) -> float | None:
    """ヤフオクの残り時間表記('7時間' '1日' '45分')を時間(float)に変換。不明はNone。

    Yahooは24時間以上を'N日'、未満を'N時間/分'で表示するため、
    '終了まで1日を切った' は返り値 < 24 で判定できる。"""
    if not text:
        return None
    m = _RE_TIME_LEFT.search(text)
    if not m:
        return None
    v, unit = float(m.group(1)), m.group(2)
    return {"日": v * 24, "時間": v, "分": v / 60, "秒": v / 3600}[unit]


def classify_form(text: str) -> str:
    """タイトルから出品形態を推定して 'loose'(カット石/ルース) か 'rough'(原石) を返す。

    判定順: ルース系の明示語 → 原石系の語 → カラット表記(=カット石が濃厚) → 既定は原石。
    ルースと原石はg単価の水準が桁違いに異なるため、相場比較の前にこれで層別する。"""
    if not text:
        return "rough"
    if _RE_LOOSE.search(text):
        return "loose"
    if _RE_ROUGH.search(text):
        return "rough"
    if _RE_CT.search(text):
        return "loose"
    return "rough"


def extract_size(text: str) -> dict:
    """テキストから size_mm_max / volume_mm3 / weight_g / weight_ct を抽出。"""
    out: dict = {
        "size_mm_max": None, "volume_mm3": None,
        "weight_g": None, "weight_ct": None, "size_raw": None,
    }
    if not text:
        return out
    raws = []

    m = _RE_DIMS.search(text)
    if m:
        unit = (m.group(4) or "mm").lower()
        dims = [float(x) for x in m.groups()[:3] if x]
        factor = 10.0 if unit in ("cm", "㎝") else 1.0
        dims_mm = [d * factor for d in dims]
        out["size_mm_max"] = max(dims_mm)
        if len(dims_mm) == 3:  # 3辺揃う時のみ体積(直方体近似)
            vol = dims_mm[0] * dims_mm[1] * dims_mm[2]
            out["volume_mm3"] = vol
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
        out["volume_mm3"] = None
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
