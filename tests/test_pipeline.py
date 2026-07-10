"""正規化・分析・保存・レポートの結合テスト(ネットワーク不要)。"""
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pandas as pd
import pytest

from mineral_tracker import analytics
from mineral_tracker.models import Listing
from mineral_tracker.normalize import extract_size


def test_extract_size_mm():
    assert extract_size("水晶クラスター 約45mm")["size_mm_max"] == 45.0
    assert extract_size("fluorite 4.5cm specimen")["size_mm_max"] == 45.0


def test_extract_dims():
    r = extract_size("アメジスト 60×40×30mm 250g")
    assert r["size_mm_max"] == 60.0
    assert r["weight_g"] == 250.0


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
    refs = analytics.reference_stats(hist, min_samples=3)
    p = report.build_report(date.today().isoformat(), listings, [], daily, refs, {})
    assert p.exists()
    assert "鉱物相場レポート" in p.read_text(encoding="utf-8")
