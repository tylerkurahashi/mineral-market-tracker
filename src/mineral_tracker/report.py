"""日次HTMLレポート生成(Plotlyグラフ埋め込み)。"""
from __future__ import annotations

import shutil
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.io as pio
from jinja2 import Template

from .config import REPORTS_DIR
from .models import Listing

TEMPLATE = Template("""<!DOCTYPE html>
<html lang="ja"><head><meta charset="utf-8">
<title>鉱物相場レポート {{ date }}</title>
<style>
 body { font-family: "Hiragino Sans", sans-serif; max-width: 1100px; margin: 2rem auto; padding: 0 1rem; color:#222; }
 h1 { border-bottom: 2px solid #7a5c3e; padding-bottom: .3rem; }
 h2 { color:#7a5c3e; margin-top:2.5rem; }
 table { border-collapse: collapse; width: 100%; font-size: .9rem; }
 th, td { border: 1px solid #ddd; padding: 6px 8px; text-align: left; }
 th { background: #f5efe8; }
 tr.bargain { background: #fff8e0; }
 .num { text-align: right; }
 .note { color:#777; font-size:.85rem; }
 img.thumb { max-height: 60px; }
</style></head><body>
<h1>鉱物相場レポート {{ date }}</h1>
<p>収集件数: {{ total }} 件 / ソース: {{ sources }}</p>

<h2>本日の買い候補(相場比 {{ threshold_pct }}% 未満)</h2>
{% if bargains %}
<table>
<tr><th>画像</th><th>種別</th><th>タイトル</th><th class="num">価格(JPY)</th><th class="num">単価</th><th class="num">相場比</th><th class="num">品質</th><th>ソース</th></tr>
{% for b in bargains %}
<tr class="bargain">
 <td>{% if b.image_urls %}<img class="thumb" src="{{ b.image_urls[0] }}">{% endif %}</td>
 <td>{{ b.species }}</td>
 <td><a href="{{ b.url }}" target="_blank">{{ b.title[:60] }}</a></td>
 <td class="num">{{ "{:,.0f}".format(b.price_jpy) }}</td>
 <td class="num">{{ b.unit_price_g and "%.0f円/g"|format(b.unit_price_g) or (b.unit_price_mm and "%.0f円/mm"|format(b.unit_price_mm)) or "-" }}</td>
 <td class="num">{{ "%.0f%%"|format(b.bargain_ratio * 100) }}</td>
 <td class="num">{{ b.q_overall if b.q_overall is not none else "-" }}</td>
 <td>{{ b.source }}</td>
</tr>
{% endfor %}
</table>
{% else %}
<p class="note">該当なし(履歴が{{ min_samples }}件未満の種別は判定されません。数日分データが貯まると検出が始まります)。</p>
{% endif %}

<h2>種別サマリー(本日)</h2>
<table>
<tr><th>種別</th><th class="num">件数</th><th class="num">中央値価格</th><th class="num">中央値 円/g</th><th class="num">基準相場 円/g (30日)</th></tr>
{% for r in summary %}
<tr><td>{{ r.species }}</td><td class="num">{{ r.n }}</td>
<td class="num">{{ "{:,.0f}".format(r.median_price) if r.median_price == r.median_price else "-" }}</td>
<td class="num">{{ "%.0f"|format(r.median_unit_g) if r.median_unit_g == r.median_unit_g else "-" }}</td>
<td class="num">{{ "%.0f"|format(r.ref_g) if r.ref_g else "-" }}</td></tr>
{% endfor %}
</table>

<h2>価格推移(種別中央値)</h2>
{{ trend_chart | safe }}

<h2>本日の価格分布</h2>
{{ dist_chart | safe }}

<p class="note">生成: mineral-market-tracker / データ: data/listings/*.parquet</p>
</body></html>""")


def build_report(
    snapshot_date: str,
    listings: list[Listing],
    bargains: list[Listing],
    daily: pd.DataFrame,
    refs: pd.DataFrame,
    analysis_cfg: dict,
) -> Path:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    today_df = pd.DataFrame([l.to_dict() for l in listings]) if listings else pd.DataFrame()

    # 種別サマリー
    summary = []
    if not today_df.empty:
        ref_map = refs.set_index("species")["median_price_g"].to_dict() if not refs.empty else {}
        for sp, g in today_df.groupby("species"):
            summary.append({
                "species": sp,
                "n": len(g),
                "median_price": pd.to_numeric(g["price_jpy"], errors="coerce").median(),
                "median_unit_g": pd.to_numeric(g["unit_price_g"], errors="coerce").median(),
                "ref_g": ref_map.get(sp),
            })

    # グラフ
    trend_html = "<p class='note'>履歴が2日分以上になるとグラフが表示されます。</p>"
    if not daily.empty and daily["snapshot_date"].nunique() >= 2:
        fig = px.line(daily, x="snapshot_date", y="median_price", color="species",
                      markers=True, labels={"median_price": "中央値価格(JPY)", "snapshot_date": "日付"})
        trend_html = pio.to_html(fig, include_plotlyjs="cdn", full_html=False)

    dist_html = "<p class='note'>本日データなし。</p>"
    if not today_df.empty:
        fig = px.box(today_df, x="species", y="price_jpy", points="outliers",
                     labels={"price_jpy": "価格(JPY)", "species": "種別"})
        fig.update_yaxes(type="log")
        dist_html = pio.to_html(fig, include_plotlyjs="cdn", full_html=False)

    html = TEMPLATE.render(
        date=snapshot_date,
        total=len(listings),
        sources=", ".join(sorted({l.source for l in listings})) or "-",
        bargains=bargains[:30],
        summary=summary,
        threshold_pct=int(analysis_cfg.get("bargain_threshold", 0.6) * 100),
        min_samples=analysis_cfg.get("min_samples", 8),
        trend_chart=trend_html,
        dist_chart=dist_html,
    )
    path = REPORTS_DIR / f"report_{snapshot_date}.html"
    path.write_text(html, encoding="utf-8")
    shutil.copy(path, REPORTS_DIR / "latest.html")
    return path
