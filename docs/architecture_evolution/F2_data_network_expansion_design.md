# F2 データネットワーク拡張設計 — 需要側ソースの汎用層登録（半導体パイロット）

> Status: **FINAL（レビュー確定 / 2026-06-17）** — DRAFT(2026-06-16) に §21.6（metadata_json 確定）／§21.7（航空機PPI 撤回）／source_type 名称統一を反映
> Depends on: ADR `external_data_access_layer.md`（ACCEPTED・push 済 origin/main=a3ff049）, F1 `F1_semiconductor_pilot_design.md`（FINAL）
> Scope: F1 で実証した「汎用層 + 共通アクセス層」の型を、**需要側の公式一次データ**へ拡張する。
> 半導体を最初のノードとし、後続のエネルギー / 暗号資産 / 地政学へ同型で横展開するための
> **反復可能なパターン**を確立する。本セッションは設計のみ（コード・DB 書き込みなし）。

---

## 1. 背景 — F1 で確定した「天井」

F1 データパレット（既存67系列）の実測で、半導体分析の射程が定量的に確定した:

- **供給側はほぼ完全に被覆**: 製品PPI `PCU334413334413`（YoY +0.41%）× 生産指数
  `IPB53122S`（YoY **+22.66%**）の2系列で、「価格が上がらない／下がるのに生産を二桁で増やせている
  ＝補助金主導の供給拡大期（供給主導ディスインフレ）」という構造を実データで判別できた。
  - **★注（§21.7）**: 旧 DRAFT は装置PPIとして `PCU336411336411`（+2.76%）を併載していたが、
    当該系列は **"PPI Aircraft Manufacturing"＝航空機**で半導体装置ではない（系列取り違え・撤回済み）。
    供給主導ディスインフレの本体は上記2系列（製品価格×生産数量）のみで成立し、この訂正の影響を受けない。
    正しい半導体装置 PPI の在庫有無は未確認（F1 §9-2 / §21.11③）。
- **需要側が盲点**: 生産+22%の「買い手」が誰か、メモリ超サイクルがどこにあるかは、
  米PPI+生産では一切答えられない。需要の信号は隣接国の輸出統計・ファウンドリ売上・
  地域別市場統計の側にある（韓国DRAM輸出 YoY +370% 等、別途確認済み）。

→ **F2 はこの盲点を、汎用層 O(1) で埋める。** 闇雲な収集ではなく「分析の穴を埋める収集」。

---

## 2. 追加する需要側ノード（3 ソース・取得方式確認済み）

| ノード | source(新規) | series_id 案 | pro_use | 取得方式（確認済み） | 粒度 | source_type | 着地先 |
|---|---|---|---|---|---|---|---|
| 韓国 半導体/メモリ輸出 | `kcs` | `KR.EXP.8541` / `KR.EXP.8542` 他 | `semi_demand_korea_export` | data.go.kr 税関OpenAPI（月次・関税コード別・毎月15日頃更新） | 月次 | `api_json`（既存型） | external_observations |
| 台湾 TSMC 月次売上 | `twse` | `TWSE.2330.REV` | `foundry_demand_proxy` | TWSE OpenAPI `t187ap05_P`（月次・当月/前月/YoY・公式JSON） | 月次 | `api_json`（既存型） | external_observations |
| WSTS 地域別半導体売上 | `wsts` | `WSTS.SALES.{AMER,EU,JP,AP}` | `semi_endmarket_sales` | Blue Book 無料Excel DL（登録不要・月次4地域） | 月次 | `file_download`（**新型**・xlsx パーサ） | external_observations |

補足候補（同型で後続追加・本パイロットでは設計のみ）:
- 台湾 同業 `TWSE.2303.REV`（UMC）等でファウンドリ全体の需要を厚く。
- 日本 製造業生産指数（e-Stat・**既存 estat 系統に相乗り可**、所在地で一次アクセス容易）。
  ※ただし estat `0004015804` に既知の日付バグ（西暦505〜517年・§21.9 未修正）があり、相乗り前に要修正。
- SEMI 装置 billings（四半期プレスは無料＝capex 先行指標。月次詳細は購読制）。

---

## 3. アーキテクチャ — 反復可能パターンの確立

### 3.1 source_type は 2 系統だけ
- **`api_json`（既存）**: 韓国KCS・台湾TWSE。既存 fetcher パターンに乗る。
  エンドポイント・認証(鍵)・レスポンス整形を per-source 設定で吸収。
- **`file_download`（新設・1 パターンで再利用）**: WSTS(Excel/xlsx) ・将来のGPR(CSV)・
  各種統計局のファイル配布。「DL → パース → 汎用層整形」の共通骨格を 1 つ作れば、
  非API ソースはすべてこの型に乗る（handover §20.8項6 の GPR 新 source_type と統合）。
  - ファイル形式（xlsx / csv 等）は `file_download` 配下のパーサ差で吸収し、source_type 自体は1つに統一する
    （旧 DRAFT の `file_xlsx` 表記は `file_download` に統一）。

### 3.2 着地は汎用層のみ（ADR 準拠）
すべて `external_observations`（`source, series_id, date, period_label, value, is_latest`）に
series 行を足すだけ。専用テーブルは作らない。読み出しは F1 で設計した共通アクセス層
（`external_observations_query.py`）が source 引数で一律に扱う。**新ノード追加の限界費用 = O(1)**。
- ★最新値の読み出しは `MAX(date)` 基準（is_latest 非依存・F1 §6）。新 source 投入時に
  is_latest が壊れても分析は無傷。

### 3.3 ネットワーク化への一般化
半導体で確立する「ノード = (source, series_id 群, pro_use, source_type, 取得設定)」という単位は、
そのままエネルギー（OPEC/EIA は既存、+各国生産・在庫）・暗号資産（オンチェーン/取引所API）・
地政学（GPR・貿易フロー）へ複製できる。**F2 は3ノードの実装であると同時に、
「ノードを足してネットワークを編む」操作の最初の実例**である。

---

## 4. カタログ登録（external_data_series への設計図追加）

新ノードはまず `external_data_series`（72行・設計図）に登録してから fetcher を配線する
（F1 の教訓: 「カタログにある＝設計済み」を先に作る）。

### 4.1 ★スキーマ確定（§21.6・read-only 実測）
`external_data_series` の実在列は以下（read-only で確認済み）:

```
id, source, series_id, name, unit, frequency, category,
pro_use, geography, metadata_json, created_at, updated_at
```

→ **`source_type` 列も `fetch_config` 列も存在しない。** したがって両者は
**`metadata_json`（JSON 列）に格納する＝スキーマ変更不要・O(1) 維持**（既定方針）。
列追加（スキーマ変更）は採らない。

### 4.2 登録内容の設計

| 項目 | 格納先 | 値 |
|---|---|---|
| source | 列 | `'kcs'` / `'twse'` / `'wsts'` |
| series_id | 列 | §2 の命名 |
| name | 列 | 人間可読名 |
| frequency | 列 | `'monthly'` |
| pro_use | 列 | §2 の軸ラベル（demand 側を明示） |
| geography | 列 | `'KR'` / `'TW'` / `'GLOBAL-{region}'` |
| **source_type** | **metadata_json** | `'api_json'` / `'file_download'`（取得方式の分岐キー） |
| **fetch_config** | **metadata_json** | エンドポイント/関税コード/DL URL/パーサ種別 等 |
| **license** | **metadata_json** | `free_redistribute` / `input_only`（§5） |

※ カタログ行の INSERT は **DB 書き込み＝別 GO**。本 doc は設計のみ。

---

## 5. ライセンス整理（再配布の可否を分けて扱う）

- **韓国KCS（data.go.kr）/ 台湾TWSE**: 政府オープンデータ。取得・分析・派生指標の表示まで
  概ね許容（各ポータルの利用規約に従う）。生値の表示も比較的自由度が高い（`free_redistribute`）。
- **WSTS**: **分析の入力には使えるが、Blue Book の生値をユーザーへ素で再配布するのは不可**（`input_only`）。
  → 実装方針: WSTS は「内部で派生指標（YoY・モメンタム・地域シェア変化）を計算する入力」に限定し、
  ユーザー画面には**加工後の指標のみ**を出す。生テーブルの素表示はしない。
- 一般原則: 各ノード登録時に `metadata_json` にライセンス区分（`free_redistribute` /
  `input_only`）を持たせ、表示層が素値表示の可否を判定できるようにする（将来の暗号資産API等で効く）。

---

## 6. 数理モデルへの接続（将来フェーズの布石）

F2 で需要×供給×価格×在庫が月次で揃うと、単純な YoY 比較を超えた分析が載る素地ができる:
- **価格×数量の弾力性推定**（供給ショックか需要ショックかの分離・F1 で芽が出た分解の定式化）。
- **先行/遅行のリード推定**（韓国20日速報・TSMC月次が米PPIに何ヶ月先行するか）。
- **地域シェアのレジーム変化検出**（WSTS 4地域の構造ブレーク）。
これらは別フェーズ。F2 はその入力データを汎用層に揃えることに徹する（実証ファースト）。

---

## 7. スコープ外（別タスク・別 GO）

- fetcher 実装（`api_json` 拡張・`file_download` 新設）＝コード変更。
- `external_data_series` への INSERT、`external_observations` への書き込み＝本番 DB 書き込み。
- **estat 日付バグ修正**（`0004015804`・西暦505年・§21.9）。日本生産指数の相乗り前提として要修復。
- **fred 系 `is_latest` 修復**（F1 §9-4）。

> ★旧 DRAFT の「F1 の既存ラベル不整合是正（`PCU336411336411`/`WPU101` の pro_use）」は**削除**。
> §21.2/§21.7 で「**ラベル不整合は無し・修正対象ゼロ**（コードは最初から正しく、`PCU336411336411` は
> aircraft、`WPU101` は metals として一貫）」と確定済み。誤っていたのはアナリストの解釈のみ。
> 残課題は「正しい半導体装置 PPI が在庫に存在するか」の確認（§21.11③）であり、ラベル是正ではない。

---

## 8. 次ステップ（read-only 先行）

1. **各 API の実レスポンス形を read-only で確認**してから fetcher を設計する
   （F1 の轍＝「形を見ずに設計」を避ける）。KCS OpenAPI / TWSE `t187ap05_P` の
   実 JSON を 1 回ずつ叩いて、series_id マッピングと date/value の取り出し位置を確定。
2. WSTS Blue Book の Excel 構造（シート/列/地域ラベル）を 1 ファイル確認。
3. 最初に配線する 1 ノードを選定（推奨: **台湾TWSE TSMC 月次**＝公式JSON・単一企業・
   即「ファウンドリ需要」軸が立つ。次に韓国KCS でメモリ需要、最後に WSTS で新 source_type）。

---

## 9. 未決

1. **〔確定済〕** `external_data_series` の `source_type`/`fetch_config`: 列は**存在しない**。
   `metadata_json` 格納でスキーマ変更不要・O(1) 維持（§4.1・§21.6）。
2. `file_download` source_type の配置（既存 jobs/ のどこに相乗りさせるか）・xlsx/csv パーサの分岐。
3. WSTS 派生指標の具体（どの加工なら再配布制約をクリアしつつ価値が出るか）。
4. ネットワーク横展開の次ノード（エネルギー or 暗号資産）の優先順位。
   ※エネルギー側は本セッションのマップ構築で WTI(`DCOILWTICO`) を in-stock 配線・米国/カタール/マラッカ等を
   verified 化済み。F2 の次ノードはマップの優先ノードと突合して選ぶ。
