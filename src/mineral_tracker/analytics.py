"""相場統計と割安検出。

ルース(カット石)と原石はg単価が桁違いに異なるため、相場は species × form で層別する。
評価指標は形態ごとに選べる(既定: ルースは体積/大きさ優先、原石は重さ優先)。"""
from __future__ import annotations

import logging
import re
from collections import Counter
from datetime import date, timedelta

import pandas as pd

from .models import Listing

logger = logging.getLogger(__name__)

_RE_KATAKANA = re.compile(r"[ァ-ヶー]{3,}")
# 鉱物名でない頻出カタカナ語(発見ノイズ)を除外。
_DISCOVERY_STOP = frozenset({
    # オークション/出品用語
    "クラスター", "ルース", "パワーストーン", "コレクション", "スタート", "サイズ",
    "ポッキリ", "ノークレーム", "ノーリターン", "セット", "オークション", "カラー",
    "タイプ", "サンプル", "ランダム", "プレゼント", "ヴィンテージ", "アンティーク",
    "ブレスレット", "ネックレス", "ペンダント", "アクセサリー",
    # 産地(origin側で扱う。species発見からは除外)
    "ブラジル", "アフガニスタン", "マダガスカル", "パキスタン", "ロシア", "ミャンマー",
    "ナミビア", "タンザニア", "メキシコ", "モロッコ", "ペルー", "ボリビア", "ウルグアイ",
    "コンゴ", "アメリカ", "ヒマラヤ", "インド", "スリランカ", "コロンビア", "ジンバブエ",
})


def discovery_terms(listings: list[Listing], top: int = 20) -> list[tuple[str, int]]:
    """未分類(species='other')のタイトルから頻出カタカナ語を抽出。追加候補の発見用。"""
    counter: Counter[str] = Counter()
    for l in listings:
        if l.species != "other":
            continue
        for tok in _RE_KATAKANA.findall(l.title or ""):
            if tok not in _DISCOVERY_STOP:
                counter[tok] += 1
    return counter.most_common(top)

# 指標名 -> (Listing属性, 基準相場カラム)
METRIC_COLS = {
    "g": ("unit_price_g", "median_price_g"),
    "mm": ("unit_price_mm", "median_price_mm"),
    "vol": ("unit_price_vol", "median_price_vol"),
}
METRIC_LABEL = {"g": "円/g", "mm": "円/mm", "vol": "円/mm³"}

# 形態ごとの指標優先順(先頭から、その出品と基準相場の両方が揃う指標を採用)
DEFAULT_METRIC_BY_FORM = {
    "loose": ["vol", "mm", "g"],   # ルースは体積/大きさ優先。無ければカラット(=重さ)
    "rough": ["g", "mm"],          # 原石は重さ優先
    "unknown": ["g", "mm"],
}


def metric_order(form: str, metric_by_form: dict | None) -> list[str]:
    cfg = metric_by_form or {}
    return cfg.get(form, DEFAULT_METRIC_BY_FORM.get(form, ["g", "mm"]))


def compute_unit_prices(listings: list[Listing]) -> None:
    for l in listings:
        if l.weight_g and l.weight_g > 0:
            l.unit_price_g = round(l.price_jpy / l.weight_g, 2)
        if l.size_mm_max and l.size_mm_max > 0:
            l.unit_price_mm = round(l.price_jpy / l.size_mm_max, 2)
        if l.volume_mm3 and l.volume_mm3 > 0:
            l.unit_price_vol = round(l.price_jpy / l.volume_mm3, 4)


def _prep_fixed(history: pd.DataFrame, dedup_listings: bool) -> pd.DataFrame:
    """相場計算用の前処理: オークション除外・日跨ぎ重複排除・form/premium列の整備。"""
    df = history.copy()
    if "listing_type" in df.columns:  # オークションは相場に入れない
        df = df[df["listing_type"] != "auction"]
    if dedup_listings and "listing_id" in df.columns and "snapshot_date" in df.columns:
        df = df.sort_values("snapshot_date").drop_duplicates("listing_id", keep="last")
    if "form" not in df.columns:
        df["form"] = "unknown"
    df["form"] = df["form"].fillna("unknown")
    if "premium" not in df.columns:
        df["premium"] = False
    df["premium"] = df["premium"].fillna(False).astype(bool)
    return df


def _medians_by(df: pd.DataFrame, keys: list[str], min_samples: int) -> pd.DataFrame:
    """指定キーでグルーピングし、各単価の中央値(外れ値上下5%除外)を出す。"""
    rows = []
    for kv, g in df.groupby(keys):
        kv = kv if isinstance(kv, tuple) else (kv,)
        rec = dict(zip(keys, kv))
        rec["n"] = len(g)
        # 各単価(円/g等)＋生価格(円)の中央値。生価格はサイズ不明のSOLD実績相場に使う。
        cols = list(METRIC_COLS.values()) + [("price_jpy", "median_price_jpy")]
        for col, out in cols:
            vals = pd.to_numeric(g[col], errors="coerce").dropna() if col in g else pd.Series(dtype=float)
            if len(vals) >= min_samples:
                lo, hi = vals.quantile(0.05), vals.quantile(0.95)
                vals = vals[(vals >= lo) & (vals <= hi)]
                rec[out] = float(vals.median())
                rec[out + "_n"] = int(len(vals))
            else:
                rec[out] = None
                rec[out + "_n"] = int(len(vals))
        rows.append(rec)
    return pd.DataFrame(rows)


def reference_stats(history: pd.DataFrame, min_samples: int,
                    dedup_listings: bool = True) -> pd.DataFrame:
    """種別×形態×特殊ごとの基準相場(直近ウィンドウの各単価の中央値)。レポート表示用。

    オークションは入札途中で価格が確定しないため除外し、固定価格のみを根拠にする。
    dedup_listings=True で同一出品の複数日スナップショットを1件に排除。
    サンプルが min_samples 未満の指標は中央値を出さない(None)。"""
    if history.empty:
        return pd.DataFrame()
    df = _prep_fixed(history, dedup_listings)
    if df.empty:
        return pd.DataFrame()
    return _medians_by(df, ["species", "form", "premium"], min_samples)


def _apply_window(df: pd.DataFrame, window_days: int | None, ref_date: date) -> pd.DataFrame:
    """直近window_daysに絞る。SOLDは売却日(sold_date)、それ以外は収集日(snapshot_date)基準。"""
    if not window_days:
        return df
    cut = (ref_date - timedelta(days=window_days)).isoformat()
    parts = []
    if "status" in df.columns:
        sold = df[df["status"] == "sold"]
        if "sold_date" in sold.columns:
            sold = sold[sold["sold_date"].fillna("") >= cut]
        parts.append(sold)
        rest = df[df["status"] != "sold"]
    else:
        rest = df
    if "snapshot_date" in rest.columns:
        rest = rest[rest["snapshot_date"].fillna("") >= cut]
    parts.append(rest)
    return pd.concat(parts) if parts else df


# 相場の探索順: 実績(SOLD)を最優先し、無ければ出品(asking)へ。各々 form+premium→form。
_BASELINE_ORDER = [("sold", "fine"), ("sold", "coarse"), ("asking", "fine"), ("asking", "coarse")]


def baseline_maps(history: pd.DataFrame, min_samples: int, dedup_listings: bool = True,
                  window_days: int | None = None, ref_date: date | None = None) -> dict:
    """相場ルックアップを basis(sold/asking)×粒度(fine/coarse) で返す。

    実績相場(SOLD)を最優先し、薄ければ出品相場(asking)にフォールバック。
    fine=(species,form,premium) / coarse=(species,form)。formは外さない。
    window_days/ref_date 指定時はその窓に絞る(SOLDは売却日基準)。"""
    if history.empty:
        return {}
    df = _prep_fixed(history, dedup_listings)
    if window_days and ref_date is not None:
        df = _apply_window(df, window_days, ref_date)
    if df.empty:
        return {}
    if "status" in df.columns:
        sold_df, ask_df = df[df["status"] == "sold"], df[df["status"] != "sold"]
    else:
        sold_df, ask_df = df.iloc[0:0], df
    maps: dict = {}
    grans = {"fine": ["species", "form", "premium"], "coarse": ["species", "form"]}
    for basis, d in (("sold", sold_df), ("asking", ask_df)):
        for gran, keys in grans.items():
            t = _medians_by(d, keys, min_samples) if not d.empty else pd.DataFrame()
            maps[(basis, gran)] = t.set_index(keys).to_dict("index") if not t.empty else {}
    return maps


def sold_price_medians(history: pd.DataFrame, windows: list[int], ref_date: date,
                       min_samples: int = 4, dedup_listings: bool = True) -> dict:
    """SOLDの生価格(円)中央値を (species,form) × 窓 で返す(実績相場テーブル用)。

    サイズ不明のSOLDは単価が出せないため生価格で集計。参考表示ゆえ min_samples は低め。
    返り値: {(species, form): {window: (median_jpy, n)}}"""
    result: dict = {}
    for w in windows:
        maps = baseline_maps(history, min_samples, dedup_listings, window_days=w, ref_date=ref_date)
        for (sp, form), r in maps.get(("sold", "coarse"), {}).items():
            if sp == "other":  # 寄せ集めは実績相場として意味がない
                continue
            v = r.get("median_price_jpy")
            if v is not None and pd.notna(v):
                result.setdefault((sp, form), {})[w] = (v, r.get("median_price_jpy_n"))
    return result


def resolve_baseline(maps: dict, species: str, form: str, premium: bool,
                     refcol: str) -> tuple[float | None, str | None]:
    """sold→asking、form+premium→form の順で相場中央値を探す。採用したbasis/粒度も返す。"""
    for basis, gran in _BASELINE_ORDER:
        m = maps.get((basis, gran), {})
        key = (species, form, premium) if gran == "fine" else (species, form)
        r = m.get(key)
        if r is not None and pd.notna(r.get(refcol)):
            return r[refcol], f"{basis}/{gran}"
    return None, None


def detect_bargains(
    listings: list[Listing],
    history: pd.DataFrame,
    threshold: float = 0.6,
    min_samples: int = 8,
    metric_by_form: dict | None = None,
    auction_max_hours_left: float = 24.0,
    dedup_listings: bool = True,
    window_days: int | None = None,
    ref_date: date | None = None,
) -> list[Listing]:
    """基準相場に対して単価が threshold 未満の現役出品を割安候補にする。

    相場は 実績(SOLD)→出品(asking)、(species,form,premium)→(species,form) の順でフォールバック。
    実際に売れた価格があればそれを最優先に比較する。
    オークションは始まったばかりだと安いだけなので、終了まで
    auction_max_hours_left 時間を切ったものだけを候補にする(固定価格は常に対象)。"""
    maps = baseline_maps(history, min_samples, dedup_listings, window_days, ref_date)
    if not any(maps.values()):
        logger.info("相場サンプル不足のため割安検出をスキップ(実績/固定価格の履歴が必要)")
        return []
    bargains = []
    for l in listings:
        # 「その他」は雑多な未分類の寄せ集めで価格水準が定まらないため相場比較しない。
        if l.species == "other":
            continue
        # SOLD(実績)は相場の材料であって現役の買い候補ではない。
        if l.status == "sold":
            continue
        # オークションは終了間際のみ候補に。早期の安値は相場を反映しないため除外。
        if l.listing_type == "auction":
            if l.ends_in_hours is None or l.ends_in_hours >= auction_max_hours_left:
                continue
        ratio = None
        for metric in metric_order(l.form, metric_by_form):
            uattr, refcol = METRIC_COLS[metric]
            uval = getattr(l, uattr, None)
            refval, _ = resolve_baseline(maps, l.species, l.form, bool(l.premium), refcol)
            if uval and refval and refval > 0:
                ratio = uval / refval
                break
        if ratio is not None and 0 < ratio < threshold:
            l.is_bargain = True
            l.bargain_ratio = round(ratio, 3)
            bargains.append(l)
    bargains.sort(key=lambda x: x.bargain_ratio or 1.0)
    return bargains


def daily_summary(history: pd.DataFrame) -> pd.DataFrame:
    """種別×日付の中央値価格推移(レポートのグラフ用)。"""
    if history.empty:
        return pd.DataFrame()
    df = history.copy()
    df["price_jpy"] = pd.to_numeric(df["price_jpy"], errors="coerce")
    return (
        df.groupby(["species", "snapshot_date"])
        .agg(
            n=("listing_id", "count"),
            median_price=("price_jpy", "median"),
            median_unit_g=("unit_price_g", lambda s: pd.to_numeric(s, errors="coerce").median()),
        )
        .reset_index()
        .sort_values(["species", "snapshot_date"])
    )
