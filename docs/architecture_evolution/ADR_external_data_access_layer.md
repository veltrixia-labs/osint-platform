# ADR: Pro 分析のデータソースを汎用層 external_observations に集約する

> Status: **ACCEPTED (方針確定 / 2026-06-16)**
> Scope: Pro 構造分析（価格圧力×産業成長、F1 半導体パイロット等）が読む
> データソースの選択。専用テーブル方式を非採用とし、汎用層 + 共通アクセス層に集約する。
> 本 ADR は方針と根拠の記録であり、実装・F1 設計ドキュメント本体の改訂は後続タスク。

---

## 1. 背景 — 2026-06-16 の ①② 調査で判明した実態

明日の F1(b) 実証ゲート（BEA/BLS データ着地）の確認中に、データ層が
**3 系統に分散し、Pro 分析が前提とする系統が死蔵**である実態が判明した。

### データ層の現状（3 系統）
- **汎用層 `external_observations`（1,951 行・稼働）**
  全ソース（fred / bls / comtrade / worldbank / census / estat / eia ...）が
  `source × series_id × date × value` で集約される共通テーブル。各 `sync_*`
  ジョブはここに書く。複数の `analysis/` モジュール（market_regime,
  macro_transmission, pro_global_series, pro_structural_context）が既にここを読む。
  スキーマ: `source, series_id, date(Date), period_label, value, is_latest`、
  unique = (source, series_id, date, period_label)。
- **準汎用層 `external_industry_stats`（371 行・稼働）**
  産業別統計。BEA GDPbyIndustry 200 行（industry_id, metric_name, year, value）と
  census CBP 171 行がここに集約される。
- **専用層 `bls_ppi_observations` / `bea_gdp_by_industry`（各 0 行・死蔵）**
  モデル・リポジトリ・クエリ（bls_ppi_query / bea_query）は実装済みだが、
  **これらを埋める書き込みジョブが配線されていない**。`sync_bls` は汎用層
  `external_observations` に書いており、専用テーブルには一切書かない。

### 致命的な発見
`pro_report_builder`（本番 Pro レポート生成）→ `analyze_price_pressure_vs_growth`
→ `get_ppi_yoy_change` / `get_industry_timeseries` の依存チェーンは、読むテーブルが
**両方とも空の専用層**。したがって「価格圧力 × 産業成長」分析は
**本番で常に `insufficient_data` を返して空回りしている**。F1(b) はこの分析を
半導体に適用する設計だったが、土台のデータ供給が断線している。

### ①②それぞれの結論
- **① FRED**: 完全回復（00:05 UTC cycle で fetched=650/saved=650）。keys 注入が奏功。
- **② BLS**: `sync_bls` の 1 行バグ（`series_ids`(None) を get_timeseries に転送 →
  fetched=0）を修正・push 済み（commit 82f4408）。修正後、BLS 6 シリーズ
  （半導体 PCU334413334413 含む 29 ヶ月分 2024-01..2026-05 月次）が
  **`external_observations`(source=bls) に landing**。ただし専用 `bls_ppi_observations`
  は依然 0（書き手不在）。
- **② BEA**: GDPbyIndustry は `external_industry_stats`(source=bea) に 200 行実在。
  ただし産業粒度は **334（電子製品全体）止まり**で、半導体ピンポイント
  3344 / 334413 は無い。334 は Value Added・年次・2022/2023 の 2 点のみ。

---

## 2. 決定

1. **Pro 分析のデータソースは汎用層 `external_observations` /
   `external_industry_stats` に集約する。** 専用テーブル
   `bls_ppi_observations` / `bea_gdp_by_industry` は**非採用**とし、
   将来のクリーンアップ候補としてマークする（今は削除しない）。

2. **共通アクセス層を 1 枚新設する。** `external_observations` から
   「source × series_id × 期間 → latest / yoy / cumulative / timeseries」を返す
   共通クエリ関数群を設ける。戻り値の形は既存 `bls_ppi_query` の関数群
   （get_ppi_latest / get_ppi_yoy_change / get_ppi_period_change が返す
   `{value, date, change_percent, ...}` 形）に合わせ、上位ロジック
   （classify_pressure_signal / analyze_price_pressure_vs_growth）を**無改造**で
   再利用できるようにする。

3. **既存の bls_ppi_query / bea_query は触らない。** 読み先変更を既存関数に
   直接加えると、それらを呼ぶ本番経路（pro_report_builder 等）への影響が
   読みきれない。新しい共通アクセス層を別に作り、F1(b) 以降の新規・改修
   分析はそちらを使う。既存専用クエリは死蔵テーブルもろとも段階的に退役。

---

## 3. 根拠

- **拡張性（最重要）**: 今後 census / OPEC / ECB / eStat 等のソースを Pro 分析に
  足すたびに専用テーブル + モデル + リポジトリ + クエリ + 書き込み配線を増やす
  方式は O(N) のコストでスケールしない。実際 BLS/BEA の専用層は実装が完結
  しないまま死蔵した。汎用層 + 共通アクセス層なら、新ソースは
  `external_observations` に series を追加するだけで O(1) で分析に載る。
- **実績**: 汎用層は全ソース集約で稼働し、複数 analysis が既に読む。
  スキーマ（source/series_id/date/period_label/value/is_latest）は YoY・累積・
  最新値の算出に必要十分。
- **最小変更で死んだ分析が蘇る**: classify_pressure_signal とその呼び出し元は
  変更不要。データ取得関数の読み先だけを汎用層に向ける（共通層経由）ことで、
  本番で空回りしている price-pressure 分析が実データで動き出す。

---

## 4. F1(b) 半導体パイロットへの適用（次セッションで設計詳細）

- **PPI 側**: 半導体 PPI `PCU334413334413` は external_observations に 29 ヶ月分
  （月次）実在。共通アクセス層経由で YoY / cumulative を実データ算出可能。
- **産業成長側（BEA）**: 半導体ピンポイント(334413)は供給されない。
  最細粒度は 334（電子製品全体・年次・2 点）。F1(b) では
  **334 を半導体の産業成長プロキシとして用いる**（年次・粗い・成長率は
  2022→2023 の 1 点 = (293.8-290.1)/290.1 ≈ +1.3% のみ）ことを設計書に明記し、
  解像度の限界を received として扱う。あるいは BEA を (b) から外し BLS PPI 単独で
  組む案も残す（次セッションで最終判断）。
- F1 設計ドキュメント `F1_semiconductor_pilot_design.md` の「データソース」節を、
  本 ADR に沿って改訂する（専用テーブル参照 → 共通アクセス層 + 汎用層参照）。

---

## 5. 未決事項（次セッション）

1. 共通アクセス層の具体的な関数シグネチャと配置（data_sources/ 配下の新モジュール）。
2. external_observations の date(Date 型) と既存 bls_ppi_query の date(文字列)の
   差異吸収の詳細。
3. BEA 334 をプロキシとする妥当性、または BLS 単独構成の最終判断。
4. F1_semiconductor_pilot_design.md 本体の改訂。
5. 死蔵テーブル（bls_ppi_observations / bea_gdp_by_industry）と関連クエリ群の
   退役計画（影響範囲: pro_report_builder → analyze_price_pressure_vs_growth 経由）。

---

## 6. 関連

- ② BLS fetch バグ修正: commit `82f4408`（fix(bls-sync): pass catalog series ids）。
- F1 設計（改訂対象）: `F1_semiconductor_pilot_design.md`。
- 影響を受ける既存コード: data_sources/{bls_ppi_query, bea_query,
  pro_price_pressure_analysis, pro_report_builder, bea_pro_analysis}.py。
