#!/usr/bin/env python3
"""日次バッチ: 収集 → 正規化 → 割安検出 → 品質評価(任意) → 保存 → レポート。"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from mineral_tracker import analytics, quality, report, storage
from mineral_tracker.collectors import COLLECTORS
from mineral_tracker.config import (
    build_species_matcher, load_sources, load_stones, sellers_by_platform,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("run_daily")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sources", nargs="*", help="実行するソース(既定: 設定でenabledのもの)")
    ap.add_argument("--quality", action="store_true", help="Claude visionによる品質評価を実行")
    ap.add_argument("--date", default=date.today().isoformat(), help="スナップショット日付")
    args = ap.parse_args()

    cfg = load_sources()
    stones = load_stones()
    exchange = cfg.get("exchange", {})
    analysis_cfg = cfg.get("analysis", {})
    quality_cfg = cfg.get("quality", {})

    # 1. 収集(カテゴリ丸ごと収集→タイトルから種を自動分類)
    matcher = build_species_matcher(stones)
    seller_ids = sellers_by_platform()  # config/sellers.yaml から platform別ID
    listings = []
    for name, cls in COLLECTORS.items():
        src_cfg = dict(cfg["sources"].get(name, {}))
        # セラーはsellers.yamlで一元管理し、収集時に注入する。
        if name == "yahoo_seller" and seller_ids.get("yahoo_seller"):
            src_cfg["sellers"] = seller_ids["yahoo_seller"]
        if name == "yahoo_flea_sold" and seller_ids.get("yahoo_flea_sold"):
            src_cfg["sold_sellers"] = seller_ids["yahoo_flea_sold"]
        enabled = src_cfg.get("enabled", False)
        if args.sources is not None:
            enabled = name in args.sources
        if not enabled:
            continue
        logger.info("=== collecting: %s ===", name)
        try:
            listings.extend(cls(src_cfg, exchange, matcher).collect(stones))
        except Exception:
            logger.exception("source %s failed entirely", name)

    if not listings:
        logger.error("収集結果が0件です。設定・APIキーを確認してください。")
        return 1
    for l in listings:
        l.snapshot_date = args.date

    # 2. 単価計算
    analytics.compute_unit_prices(listings)

    # 3. 割安検出(実績SOLD優先の相場を基準に)
    ref_date = date.fromisoformat(args.date)
    windows = analysis_cfg.get("baseline_windows", [7, 30, 90])
    bargain_window = analysis_cfg.get("bargain_window", max(windows))
    min_samples = analysis_cfg.get("min_samples", 8)
    dedup = analysis_cfg.get("baseline_dedup", True)
    history = storage.load_all()  # 全期間ロードし、窓は相場計算側で日付基準に絞る
    bargains = analytics.detect_bargains(
        listings, history,
        threshold=analysis_cfg.get("bargain_threshold", 0.6),
        min_samples=min_samples,
        metric_by_form=analysis_cfg.get("metric_by_form"),
        auction_max_hours_left=analysis_cfg.get("auction_max_hours_left", 24.0),
        dedup_listings=dedup,
        window_days=bargain_window, ref_date=ref_date,
    )
    logger.info("割安候補: %d件 (相場窓 %d日)", len(bargains), bargain_window)

    # 4. 品質評価(任意)
    if args.quality or quality_cfg.get("enabled"):
        n = quality.evaluate_batch(listings, quality_cfg)
        logger.info("品質評価: %d件", n)
        min_q = analysis_cfg.get("min_quality_score", 5.0)
        bargains = [b for b in bargains if b.q_overall is None or b.q_overall >= min_q]

    # 5. 保存
    path = storage.save_listings(listings, args.date)
    logger.info("保存: %s (%d件)", path, len(listings))

    # 6. レポート(7/30/90日など複数窓の相場を表示)
    history = storage.load_all()
    daily = analytics.daily_summary(history)
    window_maps = {
        w: analytics.baseline_maps(history, min_samples, dedup, window_days=w, ref_date=ref_date)
        for w in windows
    }
    sold_medians = analytics.sold_price_medians(history, windows, ref_date,
                                                analysis_cfg.get("sold_min_samples", 4), dedup)
    discovery = analytics.discovery_terms(listings)
    n_other = sum(1 for l in listings if l.species == "other")
    logger.info("未分類(other): %d件 / 追加候補語: %s", n_other, discovery[:8])
    rpt = report.build_report(args.date, listings, bargains, daily, window_maps, windows,
                              analysis_cfg, discovery=discovery, sold_medians=sold_medians)
    logger.info("レポート: %s", rpt)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
