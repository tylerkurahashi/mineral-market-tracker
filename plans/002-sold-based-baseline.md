# 002 SOLD実績ベースの相場

## 背景 / 動機
現状の相場は「出品中の希望価格（asking price）」から算出しており、以下のバイアスがある：
- 安い良品はすぐ売れて消え、割高な売れ残りが居座る → 相場が高く歪む（[001] の baseline_dedup で緩和したが本質は残る）
- 「いくらで出しているか」であって「いくらで売れたか」ではない

**Yahoo!フリマのSOLD（売却済み）商品**を取れば、**実際に成立した取引価格＝実績相場**になる。
これは希望価格より遥かに信頼できる相場根拠。

## 実現性（確認済み 2026-07-11）
`https://paypayfleamarket.yahoo.co.jp/user/{sellerId}` の `__NEXT_DATA__`：
- パス: `.props.initialState.searchState.search.result.items`（100件）
- **`itemStatus: "SOLD"`** が61/100件。個別ページ不要でリストから取れる
- **`endTime` = 売却日時**（SOLD品は過去日。例 `2026-01-22T11:59:13+09:00`）
- `openTime` = 出品日時、`price` = 売却価格、`title`（→種分類）、`id`
- 過去数ヶ月分のSOLDが1ページに出る → **初回で履歴をまとめて取得できる**

## 設計（既存を壊してよい前提）

### データモデル
- `Listing.status`: 既存 "active" に加え **"sold"** を使う
- `Listing.sold_date`: 追加（売却日 = endTime、YYYY-MM-DD）
- `listing_id = "yahoo_flea:{id}"`（既存フリマと同名前空間。dedupで1取引=1件）

### 収集
- 新コレクター **`YahooFleaSoldCollector`**（または yahoo_flea に sold モード）
  - config: `sellers: [ ... ]`（鉱物を扱うフリマ出品者IDのキュレーション）
  - ユーザーページを `__NEXT_DATA__` から取得、`itemStatus=="SOLD"` を抽出
  - `status="sold"`、`price_jpy=price`、`sold_date=endTime[:10]`、`listing_type="fixed"`
  - 種はタイトルから分類（既存 matcher）
- 出品者の探し方: 即決セラー同様キュレーション。将来はフリマ検索の「売り切れ表示」も検討

#### 出品者の採否基準（ユーザー方針）
「企業っぽい／販売実績あり／産地表記あり」のセラーだけを対象にする。数値で自動足切り：
- **SOLD件数** が十分（例 ≥30/直近100）＝販売実績
- **産地表記率** が高い（タイトルに『〜産』や国名。例 ≥50%）＝産地データが取れる質の高い標本商
- （店名が企業っぽいか は displayName がリストJSONに無いため補助的。上記2指標で代替）

`vet_seller(sellerId)` ヘルパーで候補を検査してから `sold_sellers` に登録する運用。

#### セラー候補（2026-07-11 検査 / scripts/vet_sellers.py）
| sellerId | SOLD | 産地表記 | 判定 |
|---|---|---|---|
| p73043487 | 61/100 | 63% | ✅ 採用 |
| p28349730 | 56/100 | 100% | ✅ 採用（探索で発見・優良） |
| p41280242 | 32/100 | 65% | ✅ 採用（探索で発見） |
| p38399661 | 27/100 | 0%（販促スタイル） | ⚠ ユーザー指定で採用（実績のみ利用） |
| p5277410 | 60/81 | 47% | ❌ 産地わずかに不足 |

**実装済み**: セラーは `config/sellers.yaml` で石種(stones.yaml)同様にリスト管理。
`scripts/vet_sellers.py` でフリマ検索→出品者頻度→SOLD/産地率を自動選別。
run_daily が platform別にIDを注入（yahoo_seller / yahoo_flea_sold）。

### 産地(origin)抽出の相乗効果
採用セラーのタイトルは『タンザニア産』『パキスタン』等 産地が明記される。SOLD収集と同時に
`extract_origin(title)` で産地を取り、将来 species×form×origin の相場や産地プレミアム分析に使える
（別途の origin 抽出タスクをここで前進できる）。

### ストレージ / 窓
- 同じParquetに保存。SOLD品は毎日再収集されるが `listing_id` dedupで1件に（1取引=1レコード）
- **窓は sold_date 基準**（いつ売れたか）で直近Nヶ月を集計。asking品は従来通り snapshot_date

### 相場計算（breaking change）
2階建てにする：
1. **実績相場（sold）= 最優先**: SOLD価格の中央値（species×form×premium）
2. **出品相場（asking）= フォールバック**: SOLD が薄い時に現行の固定価格asking中央値

`baseline_maps` を「sold優先 → asking フォールバック」に拡張。既存の
(species,form,premium)→(species,form) の段階フォールバックと直交させる：
```
実績(sold) form+premium → 実績(sold) form → 出品(asking) form+premium → 出品(asking) form
```

### 割安検出
現役出品(asking)を **実績相場(sold)** と比較：
「この石は今 X円で出ているが、同種は実際 Y円で売れている」→ 強いシグナル。
sold自身は相場の材料であって買い候補ではない。

### dedup / 二重カウント（[001]の再考）
sold は「1取引=1イベント」なので listing_id で1件に排除するのが正しい（asking の売れ残り
バイアス議論とは別。sold は keep-one が自然）。

## 未解決 / 論点
- **サイズ欠落**: ユーザーページのリストは title のみ（説明文なし）。SOLD品は size/weight が
  取れないことが多く、単価(円/g等)が出せない。当面は **species×form の生価格(price_jpy)中央値**
  で実績相場を出すのが現実的（単価より粗いが「実際いくらで売れたか」は有用）。
  必要なら SOLD item 個別ページから寸法補完（フリマ個別ページのbot耐性は要確認）。
- **窓の長さ**: sold_date ベースで何ヶ月を「現在の相場」とみなすか（既定 90日案）。
- **出品者キュレーション**: 鉱物フリマ出品者リストの初期セット（p73043487 ほか）。
- 生価格中央値は size分布に影響される（大物ばかりの月は高く出る）→ 将来 size bucket 併用。

## 段階実装
1. モデルに sold_date、収集で SOLD 取得（まず p73043487 で疎通）
2. 実績相場（生価格中央値）を baseline に組み込み、asking へフォールバック
3. レポートに「実績相場 vs 出品相場」列、割安判定を実績基準に
4. （任意）SOLD個別ページから寸法補完 → 単価ベース化

## 関連
- [001] カテゴリ収集＋多層分類。matcher / form / premium はそのまま流用
- baseline_dedup（asking用）は残す。sold は常に keep-one
