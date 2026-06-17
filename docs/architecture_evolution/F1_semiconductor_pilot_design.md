# F1 半導体パイロット設計 — 産業コスト圧力（BLS PPI 主導）

> Status: **FINAL（レビュー確定 / 2026-06-17）** — DRAFT(2026-06-16) に §21.7／①検証（is_latest）／task5 PASS を反映
> Depends on: ADR `external_data_access_layer.md`（ACCEPTED / 2026-06-16・push 済 origin/main=a3ff049）
> Scope: F1(b)。半導体の「コスト圧力局面」を**公式一次データ（BLS PPI）のみ**で
> 判定し、official-data-only でシンクタンク級の構造分析が出せることを実証する最小パイロット。
> 専用テーブル（bls_ppi_observations / bea_gdp_by_industry, 各0行・死蔵）には依存しない。

---

## 1. 目的と位置づけ

- Pro 戦略フェーズ1の槍先。「産業コスト圧力 × マクロ局面（米国中心）」のうち、
  **半導体のコスト圧力軸**を最初に作り切る。
- 実証ゲート: 汎用層 `external_observations`（稼働・実データ着地済み）から、
  共通アクセス層経由で半導体 PPI の圧力シグナルを**再現可能**に算出できること。
- 非ゴール: 本パイロット段階では本番 Pro レポートへの露出はしない（flag default-off）。
  まず型を実証し、prod 経路への展開は後段（§7）。

---

## 2. データソース（ADR 準拠）

### 2.1 採用 — classifier の hard input
- **半導体 PPI `PCU334413334413`**（`external_observations`, `source=bls`）。
  月次・2024-01〜2026-05・**29 点**。`is_latest` = 2026-05（M05・30.104）、重複なし、
  period_label は M01–M12 で健全（2026-06-17 read-only 再実測）。
  - **★is_latest は健全だが権威にしない**: bls 6系列は is_latest が正しく立っている
    （2026-06-17 実測: 全系列 n_true=1・flag_date=max_date=2026-05）。一方で
    **fred `DCOILWTICO` は is_latest が壊れている**（①の DB 突合: n_true=0）。
    バグは source/系列ローカルで、共通アクセス層は複数 source を一律に扱うため、
    **最新値はフラグでなく `MAX(date)` で取得する**（§3・§6）。is_latest は検証専用。
- アクセスは**共通アクセス層 `external_observations_query.py` 経由**。
  死蔵の専用テーブル `bls_ppi_observations`（0 行）は読まない。

### 2.2 context — 注記付き併載・hard input にしない
- **BEA 334「Computer and electronic products」Value Added**
  （`external_industry_stats`, `source=bea`）。年次 2022=290.1 / 2023=293.8 ＝ **+1.27%**。
- **不採用（classifier 入力からの除外）理由**:
  1. 半導体ピンポイント（334413 / 3344）が BEA に存在せず、最細粒度は 334（電子製品全体）。
  2. BEA GDPbyIndustry は**全 96 産業が年次 2 点のみ**＝成長率は実質 1 点で、
     粒度・鮮度・期間が PPI（月次 29 点）と構造的に不整合。これを classify に注入すると、
     古く粗い・期間ズレした成長率を起点とする偽シグナルが出る
     （撤去済み lead_lag / sanctions の「空虚シグナル」の轍）。
- → 334 は「電子製品全体の付加価値は 2022→23 で +1.3%（年次・334 集計・**半導体そのものではない**）」
  というラベル付き **context** としてのみ提示する。

---

## 3. 算出指標（共通アクセス層で計算）

| 指標 | 呼び出し | 内容 |
|---|---|---|
| latest | `get_observation_latest("bls","PCU334413334413")` | 最新値（2026-05）＝**`MAX(date)` 基準**（is_latest 非依存）|
| YoY | `get_observation_yoy("bls","PCU334413334413","2026-05")` | 2026-05 vs 2025-05 |
| cumulative | `get_observation_period_change("bls","PCU334413334413","2024-01","2026-05")` | データ域全期間の累積 |
| timeseries | `get_observation_timeseries("bls","PCU334413334413")` | 29 点（可視化・トレンド）|

- date は共通層が `"YYYY-MM"` ↔ `Date(月初)` を吸収。呼び出し側は文字列のまま扱う。
- 起点は**データ域内の 2024-01**（legacy のハードコード 2018-01 は採らない＝Blocker 1 回避）。
- **最新行の特定は `MAX(date)`**（必要なら null 値はスキップ）。`is_latest` フラグは
  source/系列により壊れている場合がある（fred 実例）ため、最新判定の権威にはしない（§2.1）。

---

## 4. 判定ロジック — PPI-only classifier（新設）

- 共有 `classify_pressure_signal` は `industry_growth` 必須（None → `insufficient_data`）。
  **これを壊さず温存**するため（ADR 決定3・既存 prod 経路に影響ゼロ）、
  F1 モジュール側に **PPI 専用の小分類器**を新設する。
- 入力: `ppi_yoy`, `ppi_cumulative`（growth 不要）。
- **暫定バンド（実装着手時に 29 点実測でキャリブレーション後に確定）**:
  - `yoy > 5` → `elevated_cost_pressure`
  - `0 < yoy ≤ 5` → `moderate_cost_pressure`
  - `yoy ≤ 0 かつ cumulative > 0` → `easing_from_elevated_base`
  - `yoy ≤ 0 かつ cumulative ≤ 0` → `cost_deflation`
  - overlay: `cumulative > 30` → `high_cumulative_flag` を付帯
  - いずれかが None → `insufficient_data`（データ欠落の正直表示）
- 注: 閾値は暫定値。実装時に `PCU334413334413` の実値で分布を確認し、
  半導体の局面に合うよう固定する（pilot ＝ 実証ファースト）。

---

## 5. 出力契約（Pro レポート断片）

```json
{
  "pilot": "f1_semiconductor_cost_pressure",
  "series_id": "PCU334413334413",
  "as_of": "2026-05",
  "latest_value": 0.0,
  "yoy_pct": null,
  "cumulative_pct_since_2024_01": null,
  "signal": "<classifier output>",
  "context": {
    "bea_334_value_added": {
      "2022": 290.1, "2023": 293.8, "growth_pct": 1.27,
      "note": "electronics aggregate (BEA 334), annual, NOT semiconductor-specific"
    },
    "resolution_note": "BEA industry growth is annual/coarse and is excluded from the signal; shown as context only."
  }
}
```

---

## 6. アーキテクチャ / 触る範囲

- **新規** `data_sources/external_observations_query.py` — 汎用アクセス層（ADR 決定2）。
  `get_observation_latest / _change / _yoy / _period_change / _timeseries`。`source` 引数化で O(1) 拡張。
  - **★最新値は `MAX(date)` で取得**（`WHERE is_latest` に依存しない）。理由: is_latest が
    壊れている系列が現存する（fred `DCOILWTICO` は n_true=0／①検証）。bls は健全だが、
    共通層は複数 source を一律処理するため、フラグ非依存が堅牢（①の WTI 読み出しガードレールと統一）。
- **新規** `data_sources/f1_semiconductor_pilot.py` — 指標算出 ＋ PPI-only classifier ＋ context 組み立て。
- **不触**: `bls_ppi_query.py` / `bea_query.py`（ADR 決定3）。
  `pro_price_pressure_analysis.py` / `pro_report_builder.py` は F1(b) では**触らない**＝prod 経路に影響ゼロ。
- **flag gate**: 本番露出は default-off の `ENABLE_F1_SEMI_PILOT`（前例 `ENABLE_LEADLAG`）で締める。
  実証中は本番非露出、ローカルでのみ評価。

---

## 7. スコープ外（別タスクに分離）

- **legacy `analyze_price_pressure_vs_growth` の蘇生**（`pro_report_builder` 経由）。
  import を共通層へ差し替え ＋ caller 日付修正（`start_year` 2018→2024 域 / `as_of_date` 2024-12→2026-05）で
  WPUFD4 / WPU101 の 2 系列が復活し得る。ただし
  (i) 半導体は `PPI_BEA_MAPPING` に未登録で要追加、
  (ii) BEA 成長率が全産業で年次 1 点＝シグナル品質が低い。
  → F1 で型を実証後、「BEA を context 降格 ＋ PPI 主導」に作り替える設計として**次段**に切る。
- **fred 系の `is_latest` 修復**（書き込み＝別 GO）。日次同期の upsert が最新行に
  `is_latest=true` を立て直せていない（`DCOILWTICO` 等）。共通層が `MAX(date)` 基準なので
  F1 の動作には影響しないが、フラグ自体の修復は別タスク（§9-4）。

---

## 8. 検証

- **ローカル read-only**（本番 DB・`DEV_MODE=true`、ポート 8011 等）で F1 モジュール出力を確認。書き込みなし。
- **BLS 定時同期（task 5）= PASS（2026-06-17 確認）**: 6/17 00:25 UTC（=09:25 JST）の定時 cron 後、
  `external_observations(bls)` の `fetched_at` が **2026-06-17 00:25 UTC へ前進**（前回の手動 sync 6/16 02:50 から）。
  全 6 系列が一律前進＝修正コード(82f4408)の定時 cron が本番 scheduler で稼働と実証。
  `last_date=2026-05` 据え置き（月次・新規行ゼロは正常）。
- **キャリブレーション**: 29 点実測で §4 バンドの妥当性を点検 → 閾値確定。

---

## 9. 未決

1. PPI-only classifier の閾値最終値（実測キャリブレーション後）。
2. **補完系列の併用可否**。注意: `PCU336411336411` は **"PPI Aircraft Manufacturing"＝航空機**であり
   **半導体製造装置ではない**（§21.7・系列取り違えとして撤回済み）。これは補完候補にしない。
   **正しい半導体装置 PPI が在庫/BLS に存在するかは未確認**（§21.11③ 持ち越し）。
   存在すれば「製品×装置」の価格乖離分析を正系列で再構成し得る。現状は `PCU334413334413` 単独。
3. 本番露出時の flag 名・配置・レポート断片の差し込み位置（pro_report_builder への接続設計）。
4. **fred 系 `is_latest` 修復**（書き込み・別 GO）。共通層が `MAX(date)` 基準なので F1 動作には非影響だが、
   フラグを正本として使う他経路があれば要修復。
