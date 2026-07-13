"""正規化・分析・保存・レポートの結合テスト(ネットワーク不要)。"""
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pandas as pd
import pytest

from mineral_tracker import analytics
from mineral_tracker.models import Listing
from mineral_tracker.config import build_species_matcher
from mineral_tracker.normalize import (
    classify_form, classify_premium, classify_species, extract_size,
    normalize_kana, parse_time_left_hours,
)

_MATCHER = build_species_matcher([
    {"species": "amethyst", "name_ja": "アメジスト", "aliases": ["紫水晶"],
     "keywords_ja": ["アメジスト 原石"], "keywords_en": ["amethyst"]},
    {"species": "quartz", "name_ja": "水晶", "keywords_ja": ["水晶 原石"], "keywords_en": ["quartz"]},
    {"species": "labradorite", "name_ja": "ラブラドライト",
     "keywords_ja": ["スペクトロライト"], "keywords_en": ["spectrolite"]},
    {"species": "villiaumite", "name_ja": "ビリオム石",
     "aliases": ["ビリオーム石", "ヴィリオーマイト"], "keywords_ja": [], "keywords_en": ["villiaumite"]},
])


def test_normalize_kana():
    assert normalize_kana("ヴィリオーマイト") == "ビリオマイト"
    assert normalize_kana("カイヤ ナイト") == "カイヤナイト"
    assert normalize_kana("ラブラドライト") == normalize_kana("ラブラドライト")


def test_classify_species():
    assert classify_species("☆ ビリオム石 ＜ロシア＞", _MATCHER) == "villiaumite"
    assert classify_species("ヴィリオーマイト ロシア産", _MATCHER) == "villiaumite"
    # 紫水晶は quartz でなく amethyst(より長い別名が優先)
    assert classify_species("紫水晶 クラスター ウルグアイ産", _MATCHER) == "amethyst"
    assert classify_species("スペクトロライト フィンランド", _MATCHER) == "labradorite"
    assert classify_species("パイライト 黄鉄鉱 ペルー産", _MATCHER) == "other"


def test_extract_size_mm():
    assert extract_size("水晶クラスター 約45mm")["size_mm_max"] == 45.0
    assert extract_size("fluorite 4.5cm specimen")["size_mm_max"] == 45.0


def test_extract_dims():
    r = extract_size("アメジスト 60×40×30mm 250g")
    assert r["size_mm_max"] == 60.0
    assert r["weight_g"] == 250.0
    assert r["volume_mm3"] == pytest.approx(60 * 40 * 30)


def test_extract_volume_only_when_three_dims():
    # 2辺だけなら体積は出さない
    assert extract_size("トパーズ 8×5mm ルース")["volume_mm3"] is None
    # cm指定は3辺ともmm換算して体積化
    assert extract_size("水晶 2×2×2cm")["volume_mm3"] == pytest.approx(20 * 20 * 20)


def test_classify_form():
    assert classify_form("アクアマリン 5.82ct 鑑別書付") == "loose"
    assert classify_form("アメジスト ルース 0.9ct") == "loose"
    assert classify_form("水晶 クラスター 原石 250g") == "rough"
    assert classify_form("ビスマス 結晶") == "rough"
    assert classify_form("トルマリン 母岩付き") == "rough"
    # ルースの明示語は原石語より優先
    assert classify_form("ガーネット ルース(結晶)") == "loose"


def test_extract_carat_to_gram():
    r = extract_size("garnet loose 5.0ct")
    assert r["weight_ct"] == 5.0
    assert r["weight_g"] == pytest.approx(1.0)


def test_extract_none():
    r = extract_size("きれいな石です")
    assert r["size_mm_max"] is None and r["weight_g"] is None


def _mk(i, species="quartz", price=1000.0, weight=10.0, day_offset=0):
    d = (date.today() - timedelta(days=day_offset)).isoformat()
    l = Listing(
        listing_id=f"test:{i}", source="test", species=species,
        title=f"{species} {weight}g", url="http://example.com",
        price_original=price, currency="JPY", price_jpy=price,
        snapshot_date=d, collected_at=d + "T00:00:00+09:00",
        weight_g=weight,
    )
    return l


def test_bargain_detection():
    # 履歴: 100円/g が相場の quartz を20件
    hist_listings = [_mk(i, price=1000.0, weight=10.0, day_offset=1) for i in range(20)]
    analytics.compute_unit_prices(hist_listings)
    history = pd.DataFrame([l.to_dict() for l in hist_listings])

    # 本日: 相場並み1件と、50円/g の激安1件
    today = [_mk("a", price=1000.0, weight=10.0), _mk("b", price=500.0, weight=10.0)]
    analytics.compute_unit_prices(today)
    bargains = analytics.detect_bargains(today, history, threshold=0.6, min_samples=8)

    assert len(bargains) == 1
    assert bargains[0].listing_id == "test:b"
    assert bargains[0].bargain_ratio == pytest.approx(0.5)


def test_classify_premium():
    assert classify_premium("パライバトルマリン ルース 0.5ct") == "パライバ"
    assert classify_premium("バイカラートルマリン 原石") == "バイカラー"
    assert classify_premium("スイカトルマリン スライス") == "スイカ"
    assert classify_premium("水晶 共生標本 母岩付き") == "共生標本"
    assert classify_premium("アメジスト 原石") is None


def test_premium_stratified_baseline():
    # 同じ tourmaline/loose でも premium は別枠の相場になる。
    plain = [_mk_form(i, "loose", 1000.0, weight=1.0) for i in range(20)]  # 標準: 1000円/g
    prem = [_mk_form(f"p{i}", "loose", 20000.0, weight=1.0) for i in range(20)]  # 特殊: 20000円/g
    for l in prem:
        l.premium = True
        l.premium_tag = "パライバ"
    analytics.compute_unit_prices(plain + prem)
    history = pd.DataFrame([l.to_dict() for l in plain + prem])

    # 特殊枠の相場(20000)に対して、特殊品を8000円/gで出すと割安。
    # もし枠が混ざっていれば中央値が跳ね上がり誤判定する。
    today = [_mk_form("cheap_prem", "loose", 8000.0, weight=1.0, day_offset=0)]
    today[0].premium = True
    today[0].premium_tag = "パライバ"
    analytics.compute_unit_prices(today)
    bargains = analytics.detect_bargains(today, history, threshold=0.6, min_samples=8)
    assert len(bargains) == 1 and bargains[0].bargain_ratio == pytest.approx(0.4)


def test_parse_time_left_hours():
    assert parse_time_left_hours("7時間") == 7.0
    assert parse_time_left_hours("1日") == 24.0
    assert parse_time_left_hours("45分") == pytest.approx(0.75)
    assert parse_time_left_hours("残り 2日") == 48.0
    assert parse_time_left_hours("") is None
    assert parse_time_left_hours("終了間近") is None


def _mk_auction(i, price, *, ends_in, weight=10.0, day_offset=0, species="quartz"):
    d = (date.today() - timedelta(days=day_offset)).isoformat()
    return Listing(
        listing_id=f"auc:{i}", source="yahoo_auctions", species=species,
        title=f"{species} {weight}g", url="http://example.com",
        price_original=price, currency="JPY", price_jpy=price,
        snapshot_date=d, collected_at=d + "T00:00:00+09:00",
        listing_type="auction", ends_in_hours=ends_in, weight_g=weight,
    )


def test_auctions_excluded_from_baseline():
    # 相場はオークションを無視する。オークションだけなら相場は立たない。
    auctions = [_mk_auction(i, 1000.0, ends_in=5.0) for i in range(20)]
    analytics.compute_unit_prices(auctions)
    hist = pd.DataFrame([l.to_dict() for l in auctions])
    assert analytics.reference_stats(hist, min_samples=8).empty


def test_auction_bargain_only_when_ending_soon():
    # 固定価格の履歴で相場(100円/g)を作る
    fixed = [_mk(i, price=1000.0, weight=10.0, day_offset=1) for i in range(20)]
    for l in fixed:
        l.listing_type = "fixed"
    analytics.compute_unit_prices(fixed)
    history = pd.DataFrame([l.to_dict() for l in fixed])

    today = [
        _mk_auction("early", 400.0, ends_in=50.0),  # 40円/g だが残り50h → 候補外
        _mk_auction("soon", 400.0, ends_in=3.0),    # 40円/g で残り3h → 候補
    ]
    analytics.compute_unit_prices(today)
    bargains = analytics.detect_bargains(today, history, threshold=0.6, min_samples=8)
    ids = {b.listing_id for b in bargains}
    assert ids == {"auc:soon"}


def _mk_form(i, form, price, *, weight=None, volume=None, day_offset=1):
    d = (date.today() - timedelta(days=day_offset)).isoformat()
    return Listing(
        listing_id=f"test:{form}:{i}", source="test", species="amethyst",
        title="amethyst", url="http://example.com",
        price_original=price, currency="JPY", price_jpy=price,
        snapshot_date=d, collected_at=d + "T00:00:00+09:00",
        form=form, weight_g=weight, volume_mm3=volume,
    )


def test_bargains_are_stratified_by_form():
    # 同一種でも rough は円/g、loose は円/mm³ で別々の基準相場になる。
    hist = (
        [_mk_form(i, "rough", 1000.0, weight=10.0) for i in range(20)]   # rough基準: 100円/g
        + [_mk_form(i, "loose", 1000.0, volume=100.0, weight=0.2) for i in range(20)]  # loose基準: 10円/mm³
    )
    analytics.compute_unit_prices(hist)
    history = pd.DataFrame([l.to_dict() for l in hist])

    today = [
        _mk_form("cheap_rough", "rough", 500.0, weight=10.0, day_offset=0),   # 50円/g → 割安
        _mk_form("normal_loose", "loose", 1000.0, volume=100.0, weight=0.2, day_offset=0),  # 10円/mm³ → 相場並み
    ]
    analytics.compute_unit_prices(today)
    bargains = analytics.detect_bargains(today, history, threshold=0.6, min_samples=8)

    ids = {b.listing_id for b in bargains}
    assert "test:rough:cheap_rough" in ids       # rough基準(円/g)で割安
    assert "test:loose:normal_loose" not in ids  # loose基準(円/mm³)では相場並み


def test_sold_baseline_preferred_over_asking():
    # 実績(SOLD)相場があれば出品(asking)相場より優先される。
    sold = [_mk_form(f"s{i}", "loose", 500.0, weight=1.0) for i in range(8)]
    for l in sold:
        l.status = "sold"
        l.sold_date = date.today().isoformat()
    ask = [_mk_form(f"a{i}", "loose", 1000.0, weight=1.0) for i in range(10)]  # status=active
    analytics.compute_unit_prices(sold + ask)
    df = pd.DataFrame([l.to_dict() for l in sold + ask])
    maps = analytics.baseline_maps(df, min_samples=8)
    val, level = analytics.resolve_baseline(maps, "amethyst", "loose", False, "median_price_g")
    assert val == 500.0 and level.startswith("sold")


def test_reference_stats_dedup_across_days():
    # 高額の売れ残り3件が5日ずつ居座り、安い10件は1日だけ、という状況。
    rows = []
    for j in range(3):        # 高額の長期出品(各5日) = 二重カウントで15観測
        for day in range(5):
            l = _mk(f"stale{j}", price=10000.0, weight=1.0, day_offset=day)
            l.listing_type = "fixed"
            rows.append(l)
    for i in range(10):       # 安い1日限りの出品10件
        l = _mk(f"cheap{i}", price=1000.0, weight=1.0)
        l.listing_type = "fixed"
        rows.append(l)
    analytics.compute_unit_prices(rows)
    df = pd.DataFrame([l.to_dict() for l in rows])

    dedup = analytics.reference_stats(df, min_samples=8, dedup_listings=True)
    nodup = analytics.reference_stats(df, min_samples=8, dedup_listings=False)
    # dedup: 高額は3件だけ → 中央値は安い側(1000)
    assert dedup.iloc[0]["median_price_g"] == 1000.0
    # 二重カウント: 高額15観測が優勢 → 中央値が跳ね上がる(相場が高く歪む)
    assert nodup.iloc[0]["median_price_g"] == 10000.0


def test_reference_stats_min_samples():
    listings = [_mk(i) for i in range(3)]
    analytics.compute_unit_prices(listings)
    df = pd.DataFrame([l.to_dict() for l in listings])
    refs = analytics.reference_stats(df, min_samples=8)
    assert refs.iloc[0]["median_price_g"] is None or pd.isna(refs.iloc[0]["median_price_g"])


def test_storage_roundtrip(tmp_path, monkeypatch):
    from mineral_tracker import storage
    monkeypatch.setattr(storage, "LISTINGS_DIR", tmp_path / "listings")
    listings = [_mk(i) for i in range(5)] + [_mk(0)]  # 重複1件
    storage.save_listings(listings, date.today().isoformat())
    df = storage.load_all()
    assert len(df) == 5  # 重複排除される


def test_report_build(tmp_path, monkeypatch):
    from mineral_tracker import report
    monkeypatch.setattr(report, "REPORTS_DIR", tmp_path)
    listings = [_mk(i) for i in range(5)]
    analytics.compute_unit_prices(listings)
    hist = pd.DataFrame([l.to_dict() for l in listings])
    daily = analytics.daily_summary(hist)
    windows = [7, 30]
    window_maps = {w: analytics.baseline_maps(hist, min_samples=3) for w in windows}
    p = report.build_report(date.today().isoformat(), listings, [], daily, window_maps, windows, {})
    assert p.exists()
    assert "鉱物相場レポート" in p.read_text(encoding="utf-8")


def test_baseline_fallback_premium_to_form():
    # premium枠が薄い(2件<8)ときは (species,form) 相場を借りて判定する。
    hist = [_mk_form(i, "loose", 1000.0, weight=1.0) for i in range(10)]  # 非premium 1000円/g
    prem = [_mk_form(f"p{i}", "loose", 20000.0, weight=1.0) for i in range(2)]  # premium 2件のみ
    for l in prem:
        l.premium = True
        l.premium_tag = "パライバ"
    analytics.compute_unit_prices(hist + prem)
    history = pd.DataFrame([l.to_dict() for l in hist + prem])

    today = [_mk_form("cheap_prem", "loose", 500.0, weight=1.0, day_offset=0)]
    today[0].premium = True
    today[0].premium_tag = "パライバ"
    analytics.compute_unit_prices(today)

    bargains = analytics.detect_bargains(today, history, threshold=0.6, min_samples=8)
    # premium専用相場は2件で立たないが、(loose)へフォールバックして 500/1000=0.5 で割安判定
    assert len(bargains) == 1 and bargains[0].bargain_ratio == pytest.approx(0.5)
