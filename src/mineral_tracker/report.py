"""日次HTMLレポート生成(Plotlyグラフ埋め込み)。"""
from __future__ import annotations

import shutil
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.io as pio
from jinja2 import Template

from .analytics import METRIC_COLS, METRIC_LABEL, metric_order, resolve_baseline
from .config import REPORTS_DIR
from .models import Listing

FORM_LABEL = {"loose": "ルース", "rough": "原石", "unknown": "不明"}

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
<tr><th>画像</th><th>種別</th><th>形態</th><th>タイトル</th><th class="num">価格(JPY)</th><th class="num">単価</th><th class="num">相場比</th><th class="num">品質</th><th>ソース</th></tr>
{% for b in bargains %}
<tr class="bargain">
 <td>{% if b.image_urls %}<img class="thumb" src="{{ b.image_urls[0] }}">{% endif %}</td>
 <td>{{ b.species }}</td>
 <td>{{ form_labels.get(b.form, b.form) }}{% if b.premium_tag %} <span style="color:#b00">[{{ b.premium_tag }}]</span>{% endif %}</td>
 <td><a href="{{ b.url }}" target="_blank">{{ b.title[:60] }}</a></td>
 <td class="num">{{ "{:,.0f}".format(b.price_jpy) }}</td>
 <td class="num">{{ b.unit_price_vol and "%.2f円/mm³"|format(b.unit_price_vol) or (b.unit_price_g and "%.0f円/g"|format(b.unit_price_g)) or (b.unit_price_mm and "%.0f円/mm"|format(b.unit_price_mm)) or "-" }}</td>
 <td class="num">{{ "%.0f%%"|format(b.bargain_ratio * 100) }}</td>
 <td class="num">{{ b.q_overall if b.q_overall is not none else "-" }}</td>
 <td>{{ b.source }}</td>
</tr>
{% endfor %}
</table>
{% else %}
<p class="note">該当なし(履歴が{{ min_samples }}件未満の種別は判定されません。数日分データが貯まると検出が始まります)。</p>
{% endif %}

<h2>種別×形態サマリー(本日)</h2>
<p class="note">ルース/原石は単価水準が桁違いのため層別。指標: 体積(円/mm³)・大きさ(円/mm)・重さ(円/g)。
相場は実績(SOLD)優先→出品(asking)。<b>*</b>は出品相場を借りた印。窓ごとに 7/30/90日の相場を表示。</p>
<table>
<tr><th>種別</th><th>形態</th><th class="num">件数</th><th class="num">中央値価格</th><th>指標</th><th class="num">本日単価</th>
{% for w in windows %}<th class="num">相場{{ w }}d</th>{% endfor %}</tr>
{% for r in summary %}
<tr><td>{{ r.species }}</td><td>{{ r.form_label }}</td><td class="num">{{ r.n }}</td>
<td class="num">{{ "{:,.0f}".format(r.median_price) if r.median_price == r.median_price else "-" }}</td>
<td>{{ r.metric_label }}</td>
<td class="num">{{ r.today_unit_fmt }}</td>
{% for w in windows %}<td class="num">{{ r.ref_by_window[w] }}</td>{% endfor %}</tr>
{% endfor %}
</table>

<h2>実績相場(SOLD 売却価格の中央値・円)</h2>
<p class="note">フリマで実際に売れた価格の中央値。窓は売却日基準(7/30/90日)。
サイズ情報が無いため生価格(円)ベース＝size分布の影響を受ける参考値。()内は件数。</p>
{% if sold_summary %}
<table>
<tr><th>種別</th><th>形態</th>{% for w in windows %}<th class="num">{{ w }}日</th>{% endfor %}</tr>
{% for r in sold_summary %}
<tr><td>{{ r.species }}</td><td>{{ r.form_label }}</td>
{% for w in windows %}<td class="num">{{ r.by_window[w] }}</td>{% endfor %}</tr>
{% endfor %}
</table>
{% else %}
<p class="note">SOLD実績がまだありません(フリマSOLD収集を数日回すと貯まります)。</p>
{% endif %}

<h2>未分類からの発見(追加候補)</h2>
<p class="note">カテゴリ収集で種を判定できなかった出品({{ n_other }}件)の頻出語。
辞書に無い鉱物が上位に出たら stones.yaml に追加候補。</p>
{% if discovery %}
<table>
<tr><th>頻出語</th><th class="num">件数</th></tr>
{% for term, cnt in discovery %}
<tr><td>{{ term }}</td><td class="num">{{ cnt }}</td></tr>
{% endfor %}
</table>
{% else %}
<p class="note">未分類なし。</p>
{% endif %}

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
    window_maps: dict,
    windows: list[int],
    analysis_cfg: dict,
    discovery: list[tuple[str, int]] | None = None,
    sold_medians: dict | None = None,
) -> Path:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    today_df = pd.DataFrame([l.to_dict() for l in listings]) if listings else pd.DataFrame()
    primary = windows[-1] if windows else None  # 最長窓(最もデータが多い)で指標を選ぶ

    def _fmt_ref(maps, sp, form, prem, refcol, fmt):
        v, level = resolve_baseline(maps, sp, form, prem, refcol)
        if not v:
            return "-"
        s = fmt % v
        if level and level.startswith("asking"):  # 出品相場を借りた印
            s += "*"
        return s

    # 種別×形態サマリー(相場は実績SOLD優先→出品asking、7/30/90日の窓別)
    metric_by_form = analysis_cfg.get("metric_by_form")
    summary = []
    if not today_df.empty:
        if "form" not in today_df.columns:
            today_df["form"] = "unknown"
        today_df["form"] = today_df["form"].fillna("unknown")
        if "premium" not in today_df.columns:
            today_df["premium"] = False
        today_df["premium"] = today_df["premium"].fillna(False).astype(bool)
        pmaps = window_maps.get(primary, {})
        for (sp, form, premium), g in today_df.groupby(["species", "form", "premium"]):
            order = metric_order(form, metric_by_form)
            # 最長窓で相場が引ける指標を優先、無ければ本日値がある指標、最後に先頭。
            metric = next(
                (m for m in order if resolve_baseline(pmaps, sp, form, bool(premium), METRIC_COLS[m][1])[0] is not None),
                None)
            if metric is None:
                metric = next(
                    (m for m in order if pd.to_numeric(g[METRIC_COLS[m][0]], errors="coerce").notna().any()),
                    order[0])
            ucol, refcol = METRIC_COLS[metric]
            today_unit = pd.to_numeric(g[ucol], errors="coerce").median() if ucol in g else float("nan")
            fmt = "%.2f" if metric == "vol" else "%.0f"
            label = FORM_LABEL.get(form, form)
            if premium:  # 別枠(特殊要素)。代表的なタグを併記
                tags = g["premium_tag"].dropna() if "premium_tag" in g else pd.Series(dtype=str)
                label += f"・特殊({tags.mode().iat[0]})" if not tags.empty else "・特殊"
            ref_by_window = {
                w: _fmt_ref(window_maps.get(w, {}), sp, form, bool(premium), refcol, fmt)
                for w in windows
            }
            summary.append({
                "species": sp,
                "form_label": label,
                "n": len(g),
                "median_price": pd.to_numeric(g["price_jpy"], errors="coerce").median(),
                "metric_label": METRIC_LABEL[metric],
                "today_unit_fmt": (fmt % today_unit) if today_unit == today_unit else "-",
                "ref_by_window": ref_by_window,
            })
        summary.sort(key=lambda r: (r["species"], r["form_label"]))

    # 実績相場(SOLD): 生価格(円)中央値を species×form × 窓 で
    sold_medians = sold_medians or {}
    sold_summary = []
    for sp, form in sorted(sold_medians.keys()):
        wv = sold_medians[(sp, form)]
        by_window = {}
        for w in windows:
            if w in wv:
                v, n = wv[w]
                by_window[w] = f"{v:,.0f}円({n})"
            else:
                by_window[w] = "-"
        sold_summary.append({"species": sp, "form_label": FORM_LABEL.get(form, form),
                             "by_window": by_window})

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
        sold_summary=sold_summary,
        windows=windows,
        form_labels=FORM_LABEL,
        threshold_pct=int(analysis_cfg.get("bargain_threshold", 0.6) * 100),
        min_samples=analysis_cfg.get("min_samples", 8),
        trend_chart=trend_html,
        dist_chart=dist_html,
        discovery=discovery or [],
        n_other=sum(1 for l in listings if l.species == "other"),
    )
    path = REPORTS_DIR / f"report_{snapshot_date}.html"
    path.write_text(html, encoding="utf-8")
    shutil.copy(path, REPORTS_DIR / "latest.html")
    return path
