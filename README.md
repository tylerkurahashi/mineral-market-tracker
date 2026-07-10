# mineral-market-tracker

ルース・鉱物標本の相場を毎日収集・記録し、割安商品をピックアップするツール。

## セットアップ

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e .
cp .env.example .env   # APIキーを設定
```

## 使い方

```bash
# 日次バッチ(収集→保存→分析→レポート)
python scripts/run_daily.py

# 品質評価(Claude vision)も実行する場合
python scripts/run_daily.py --quality

# 特定ソースのみ
python scripts/run_daily.py --sources ebay

# 保存済みデータへのSQL照会例
python scripts/query.py "SELECT species, count(*), median(price_jpy) FROM listings GROUP BY species"
```

## 出力

- `data/listings/date=YYYY-MM-DD/*.parquet` — 日次の出品スナップショット
- `reports/report_YYYY-MM-DD.html` — 相場レポート(価格推移・分布・買い候補)
- `reports/latest.html` — 最新レポートへのコピー

## 設定

- `config/stones.yaml` — 追跡する鉱物と検索キーワード(和英)
- `config/sources.yaml` — データソースのON/OFF・パラメータ
- `.env` — `EBAY_CLIENT_ID` / `EBAY_CLIENT_SECRET` / `ANTHROPIC_API_KEY`

## GitHub Actions

`.github/workflows/daily.yml` が毎日 UTC 21:00(JST 6:00)に実行し、
データとレポートをリポジトリにcommitします。リポジトリのSecretsに
`EBAY_CLIENT_ID` / `EBAY_CLIENT_SECRET`(品質評価を使うなら `ANTHROPIC_API_KEY`)を登録してください。

## 注意

- ヤフオクには公式APIがなく、ページ取得は規約変更等のリスクがあります。低頻度・低負荷で自己責任で運用してください。
- 詳細な設計は `PLAN.md` を参照。
