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
from mineral_tracker.config import load_sources, load_stones

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

    # 1. 収集
    listings = []
    for name, cls in COLLECTORS.items():
        src_cfg = cfg["sources"].get(name, {})
        enabled = src_cfg.get("enabled", False)
        if args.sources is not None:
            enabled = name in args.sources
        if not enabled:
            continue
        logger.info("=== collecting: %s ===", name)
        try:
            listings.extend(cls(src_cfg, exchange).collect(stones))
        except Exception:
            logger.exception("source %s failed entirely", name)

    if not listings:
        logger.error("収集結果が0件です。設定・APIキーを確認してください。")
        return 1
    for l in listings:
        l.snapshot_date = args.date

    # 2. 単価計算
    analytics.compute_unit_prices(listings)

    # 3. 割安検出(過去データを基準に)
    history = storage.load_all(window_days=analysis_cfg.get("window_days", 30))
    bargains = analytics.detect_bargains(
        listings, history,
        threshold=analysis_cfg.get("bargain_threshold", 0.6),
        min_samples=analysis_cfg.get("min_samples", 8),
    )
    logger.info("割安候補: %d件", len(bargains))

    # 4. 品質評価(任意)
    if args.quality or quality_cfg.get("enabled"):
        n = quality.evaluate_batch(listings, quality_cfg)
        logger.info("品質評価: %d件", n)
        min_q = analysis_cfg.get("min_quality_score", 5.0)
        bargains = [b for b in bargains if b.q_overall is None or b.q_overall >= min_q]

    # 5. 保存
    path = storage.save_listings(listings, args.date)
    logger.info("保存: %s (%d件)", path, len(listings))

    # 6. レポート
    history = storage.load_all(window_days=analysis_cfg.get("window_days", 30))
    daily = analytics.daily_summary(history)
    refs = analytics.reference_stats(history, analysis_cfg.get("min_samples", 8))
    rpt = report.build_report(args.date, listings, bargains, daily, refs, analysis_cfg)
    logger.info("レポート: %s", rpt)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
