# BEA NIPA Observations — Storage Design

## 概要

BEA API から取得した NIPA (National Income and Product Accounts) データをDBに格納するためのテーブル設計。
NIPA は GDP、個人消費支出 (PCE)、投資、政府支出などのマクロ経済指標を包含し、単位（成長率、実額、指数）やスケール（百万、1.0など）が多岐にわたるため、これらを正確に保持し分析に活用できる設計とする。

---

## 1. テーブル設計

### テーブル名: `bea_nipa_observations`

| # | カラム名 | 型 | NOT NULL | 説明 |
|---|---------|------|----------|------|
| 1 | `id` | UUID | ✅ | PK. `uuid4()` auto-generated |
| 2 | `dataset_name` | String(64) | ✅ | BEA dataset 識別子 (e.g. `"NIPA"`) |
| 3 | `table_name` | String(16) | ✅ | NIPA Table ID (e.g. `"T10101"`, `"T10105"`) |
| 4 | `series_code` | String(16) | ❌ | 指標固有のコード (e.g. `"A191RC"`, `"DPCERC"`) |
| 5 | `line_number` | String(8) | ✅ | テーブル内の行番号。指標の特定に使用 |
| 6 | `line_description` | String(256) | ❌ | 指標の説明 (e.g. `"Gross domestic product"`) |
| 7 | `time_period` | String(16) | ✅ | 観測期間 (e.g. `"2024"`, `"2024Q1"`) |
| 8 | `frequency` | String(4) | ✅ | `"A"` (Annual) / `"Q"` (Quarterly) / `"M"` (Monthly) |
| 9 | `metric_name` | String(64) | ❌ | 単位の種類 (e.g. `"Current Dollars"`, `"Fisher Quantity Index"`) |
| 10 | `cl_unit` | String(64) | ❌ | 単位の表現 (e.g. `"Level"`, `"Percent change, annual rate"`) |
| 11 | `unit_mult` | Integer | ❌ | 単位の倍率 (e.g. `6` = 百万単位, `0` = 1.0) |
| 12 | `data_value` | Float | ❌ | 数値データ。変換不可時は `NULL` |
| 13 | `note_ref` | String(32) | ❌ | BEA NoteRef |
| 14 | `statistic` | String(128) | ❌ | BEA Statistic フィールド (e.g. `"NIPA Table"`) |
| 15 | `utc_production_time` | String(32) | ❌ | BEA レスポンスの生成日時 |
| 16 | `fetched_at` | DateTime(tz) | ✅ | データ取得日時。`server_default=func.now()` |
| 17 | `raw_json` | JSON | ❌ | 元の行データ (デバッグ・監査用) |

---

## 2. UNIQUE 制約

```sql
UNIQUE (dataset_name, table_name, line_number, time_period, frequency)
```

**制約名**: `uq_bea_nipa_data_point`

### 理由

NIPA において、同一の Table 内の LineNumber は特定の概念（例：GDP、耐久財、サービス）を指し示す。
これに観測時点 (`time_period`, `frequency`) を組み合わせることで、一意のデータポイントが定まる。

- **series_code を含めない理由**: `series_code` は改定時に変更される可能性があるが、`line_number` はテーブル構造が維持される限り安定しているため、制約の主軸には `line_number` を採用する。
- **UPSERT の実現**: この制約により、同一テーブルの同一期間データを再取得した際に `data_value` を更新 (UPDATE) することが可能になる。

---

## 3. Index 設計

| Index 名 | カラム | 種別 | 用途 |
|----------|--------|------|------|
| `uq_bea_nipa_data_point` | `(dataset_name, table_name, line_number, time_period, frequency)` | UNIQUE | 重複防止 + UPSERT キー |
| `ix_bea_nipa_table_line` | `(table_name, line_number)` | B-tree | 特定の指標の時系列推移を抽出するクエリの高速化 |
| `ix_bea_nipa_table_period`| `(table_name, time_period)` | B-tree | 特定の時点のテーブル全項目を比較するクエリの高速化 |
| `ix_bea_nipa_series_code` | `(series_code)` | B-tree | `series_code` による直接検索（外部データとの紐付け等） |
| `ix_bea_nipa_fetched_at` | `(fetched_at)` | B-tree | データ鮮度管理 |

---

## 4. 単位・スケールの扱い

NIPA は `GDPbyIndustry` 以上に単位の解釈が重要となる。

- **`unit_mult` (倍率)**:
    - `6` の場合、`data_value` に $10^6$ (100万) を掛ける必要がある。
    - Pro 分析レイヤーでは、これを用いて一貫した "Dollars" (実額) に変換して集計・比較を行う。
- **`cl_unit` / `metric_name`**:
    - `"Percent change"` と `"Level"` が混在するため、これらを無視して合計を取ると誤った結果になる。
    - クエリ層では必ず `cl_unit` や `metric_name` でフィルタリングを行う。

---

## 5. 推奨 DDL

### PostgreSQL

```sql
CREATE TABLE bea_nipa_observations (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    dataset_name    VARCHAR(64) NOT NULL,
    table_name      VARCHAR(16) NOT NULL,
    series_code     VARCHAR(16),
    line_number     VARCHAR(8)  NOT NULL,
    line_description VARCHAR(256),
    time_period     VARCHAR(16) NOT NULL,
    frequency       VARCHAR(4)  NOT NULL,
    metric_name     VARCHAR(64),
    cl_unit         VARCHAR(64),
    unit_mult       INTEGER,
    data_value      DOUBLE PRECISION,
    note_ref        VARCHAR(32),
    statistic       VARCHAR(128),
    utc_production_time VARCHAR(32),
    fetched_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    raw_json        JSONB,

    CONSTRAINT uq_bea_nipa_data_point
        UNIQUE (dataset_name, table_name, line_number, time_period, frequency)
);

CREATE INDEX ix_bea_nipa_table_line   ON bea_nipa_observations (table_name, line_number);
CREATE INDEX ix_bea_nipa_table_period ON bea_nipa_observations (table_name, time_period);
CREATE INDEX ix_bea_nipa_series_code  ON bea_nipa_observations (series_code);
CREATE INDEX ix_bea_nipa_fetched_at   ON bea_nipa_observations (fetched_at);
```

---

## 6. 将来拡張と注意点

### 6.1 raw_json の保持
初期段階では監査用に `raw_json` を保持するが、NIPA はテーブル数が多いためデータ量が `GDPbyIndustry` より早く膨らむ可能性がある。将来的にストレージコストが課題となった場合は `raw_json` の削除を検討する。

### 6.2 TableName の追加
TableName (T10101, T10105 等) を追加しても、このスキーマで全ての NIPA データが格納可能である。

### 6.3 次のステップへの注意
- **モデル定義**: `db/models.py` に `BEANipaObservation` クラスを追加。
- **マイグレーション**: `alembic revision --autogenerate` を実行。
- **独立性**: 既存の `bea_gdp_by_industry` とは別テーブルとし、マクロ(NIPA)と産業(GDPbyIndustry)をクエリ層で統合する。
