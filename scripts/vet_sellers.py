#!/usr/bin/env python3
"""Yahoo!フリマの鉱物出品者を探索し、SOLD実績相場のセラー候補を選別する。

フリマ検索で鉱物系キーワードを引き、結果から出品者IDを頻度集計 →
各候補のユーザーページを見て「SOLD件数」「産地表記率」を評価 →
基準(既定 SOLD>=30/100・産地>=50%)を満たすものを候補として表示する。

フリマは連打で一時BANされるため間隔を広めに(既定6s)。
"""
from __future__ import annotations

import argparse
import json
import re
import time
from collections import Counter
from urllib.parse import quote

import requests

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
SEARCH = "https://paypayfleamarket.yahoo.co.jp/search/{kw}"
USER = "https://paypayfleamarket.yahoo.co.jp/user/{sid}"
_RE_NEXT = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)
_RE_ORIGIN = re.compile(
    r"産|ブラジル|マダガスカル|コンゴ|ロシア|パキスタン|タンザニア|中国|メキシコ|ペルー|"
    r"アメリカ|ナミビア|モロッコ|アフガニスタン|スペイン|ネパール|インド|ミャンマー|"
    r"Brazil|Congo|Russia|Pakistan|China"
)


def _items(html: str) -> list[dict]:
    m = _RE_NEXT.search(html)
    if not m:
        return []
    try:
        return json.loads(m.group(1))["props"]["initialState"]["searchState"]["search"]["result"]["items"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return []


def _get(url: str, interval: float) -> str | None:
    r = requests.get(url, headers={"User-Agent": UA}, timeout=30)
    time.sleep(interval)
    if r.status_code != 200:
        print(f"  ! {r.status_code} {url}")
        return None
    return r.text


def vet(sid: str, interval: float) -> dict | None:
    html = _get(USER.format(sid=sid), interval)
    if not html:
        return None
    items = _items(html)
    if not items:
        return None
    sold = sum(1 for i in items if i.get("itemStatus") == "SOLD")
    origin = sum(1 for i in items if _RE_ORIGIN.search(i.get("title", "")))
    return {"id": sid, "n": len(items), "sold": sold, "origin_pct": round(100 * origin / len(items))}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--keywords", nargs="*", default=["鉱物 標本", "原石 鉱物 標本", "鉱物標本 産"])
    ap.add_argument("--top", type=int, default=8, help="頻度上位いくつを検査するか")
    ap.add_argument("--interval", type=float, default=6.0)
    ap.add_argument("--min-sold", type=int, default=30)
    ap.add_argument("--min-origin", type=int, default=50)
    ap.add_argument("--exclude", nargs="*", default=[], help="検査から除外する既知sellerId")
    args = ap.parse_args()
    exclude = set(args.exclude)

    freq: Counter[str] = Counter()
    for kw in args.keywords:
        html = _get(SEARCH.format(kw=quote(kw)), args.interval)
        its = _items(html) if html else []
        for it in its:
            sid = it.get("sellerId")
            if sid:
                freq[sid] += 1
        print(f"検索 '{kw}': {len(its)}件, 出品者 {len(set(i.get('sellerId') for i in its))}人")

    print(f"\n頻出出品者(既知{len(exclude)}人を除外) 上位{args.top} を検査...")
    rows = []
    for sid, cnt in [(s, c) for s, c in freq.most_common() if s not in exclude][:args.top]:
        info = vet(sid, args.interval)
        if info:
            info["freq"] = cnt
            ok = info["sold"] >= args.min_sold and info["origin_pct"] >= args.min_origin
            info["verdict"] = "✅採用" if ok else "❌除外"
            rows.append(info)

    rows.sort(key=lambda r: (r["verdict"].startswith("✅"), r["sold"]), reverse=True)
    print(f"\n{'sellerId':32}{'出現':>4}{'SOLD':>6}{'産地%':>6}  判定")
    for r in rows:
        print(f"{r['id']:32}{r['freq']:>4}{r['sold']:>4}/{r['n']:<3}{r['origin_pct']:>5}%  {r['verdict']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
