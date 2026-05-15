# BLS PPI Observations — Storage Design

## 概要

BLS (Bureau of Labor Statistics) から取得した PPI (Producer Price Index) データをDBに格納するためのテーブル設計。
PPI は月次の指数データであり、製造コストや原材料価格の変動を産業別に把握するための「価格圧力レイヤー」として活用される。
BEA の実質・名目成長率データと組み合わせることで、コスト増がマージンを圧迫しているか等の高度な分析を可能にする。

---

## 1. テーブル設計

### テーブル名: `bls_ppi_observations`

| # | カラム名 | 型 | NOT NULL | 説明 |
|---|---------|------|----------|------|
| 1 | `id` | UUID | ✅ | PK. `uuid4()` auto-generated |
| 2 | `source` | String(16) | ✅ | データソース (e.g. `"BLS"`) |
| 3 | `dataset_name` | String(32) | ✅ | データセット識別子 (e.g. `"PPI"`) |
| 4 | `series_id` | String(32) | ✅ | BLS Series ID (e.g. `"WPUFD4"`) |
| 5 | `series_name` | String(256) | ❌ | 指標名称 (e.g. `"PPI Final demand"`) |
| 6 | `year` | Integer | ✅ | 観測年 |
| 7 | `period` | String(4) | ✅ | 月次コード (e.g. `"M01"` 〜 `"M12"`) |
| 8 | `period_name` | String(16) | ❌ | 月名称 (e.g. `"January"`) |
| 9 | `date` | String(10) | ✅ | 検索・ソート用日付文字列 (`"YYYY-MM"`) |
| 10 | `value` | Float | ❌ | 指数値 (Index value) |
| 11 | `footnotes` | JSON | ❌ | 補足情報 (BLS API からの配列) |
| 12 | `latest` | Boolean | ✅ | 最新観測値フラグ |
| 13 | `fetched_at` | DateTime(tz) | ✅ | データ取得日時。`server_default=func.now()` |
| 14 | `raw_json` | JSON | ❌ | 元の行データ (デバッグ・監査用) |

---

## 2. UNIQUE 制約

```sql
UNIQUE (source, dataset_name, series_id, date)
```

**制約名**: `uq_bls_ppi_data_point`

### 理由

BLS において、特定の Series ID に対する年月 (`date`) は一意の観測値を表す。
将来的に CPI (Consumer Price Index) や Employment (雇用) などの別データセット (`dataset_name`) を追加した場合や、ソース (`source`) が異なる類似指標を取得した場合でも衝突を避けるため、4カラムの複合キーとする。

これに基づき **UPSERT (INSERT ... ON CONFLICT UPDATE)** を行うことで、最新の改定値や最新フラグの状態を安全に同期できる。

---

## 3. Index 設計

| Index 名 | カラム | 種別 | 用途 |
|----------|--------|------|------|
| `uq_bls_ppi_data_point` | `(source, dataset_name, series_id, date)` | UNIQUE | 重複防止 + UPSERT キー |
| `ix_bls_ppi_series_date` | `(series_id, date)` | B-tree | 特定指標の時系列推移の抽出 |
| `ix_bls_ppi_date` | `(date)` | B-tree | 特定の月の全産業価格変動の横断比較 |
| `ix_bls_ppi_latest` | `(latest)` | B-tree | `latest=true` のみの高速抽出 (ダッシュボード表示用) |
| `ix_bls_ppi_fetched_at` | `(fetched_at)` | B-tree | データ鮮度管理 |

---

## 4. 特殊フラグとデータの扱い

### 4.1 `latest` フラグ
- 新しい月のデータを取得した際、既存の同一 `series_id` の `latest` を `false` に更新し、新着行を `true` に設定する。
- これにより、クエリ側で `where latest = true` とするだけで全シリーズの最新状況を即座に把握できる。

### 4.2 `date` (String)
- SQLite と PostgreSQL の互換性、および BEA データの `year` (String) との JOIN のしやすさを考慮し、`"YYYY-MM"` 形式の文字列を採用する。
- アルファベット順のソートが時系列順と一致するため、範囲検索や時系列抽出に実害はない。

### 4.3 `footnotes` & `raw_json`
- `footnotes` は BLS 特有の注釈情報を保持し、表示時に利用する。
- `raw_json` は監査用だが、PPI は 10年分でも 120行/シリーズ 程度と非常に軽量なため、長期間保持してもストレージ負荷は低い。

---

## 5. BEA GDPbyIndustry との統合 (Mapping 方針)

PPI (`bls_ppi_observations`) と BEA 産業データ (`bea_gdp_by_industry`) は、直接的な FOREIGN KEY ではなく、**コードマッピング**によって統合する。

- **対応表 (Logic Layer)**:
    - `WPUFD49104 (Goods)` ↔ `31G (Manufacturing)`
    - `WPU057 (Fuels)` ↔ `22 (Utilities)`
    - `WPU117 (Electronic components)` ↔ `51 (Information)`
- **分析手順**:
    1. 同一期間の BEA `data_value` (名目成長) と PPI `value` (価格変動) を取得。
    2. PPI の前年比 (YoY) を算出し、BEA の成長が「実質的な生産増」か「価格転嫁によるもの」かを推定。

---

## 6. 推奨 DDL (PostgreSQL)

```sql
CREATE TABLE bls_ppi_observations (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    source          VARCHAR(16) NOT NULL,
    dataset_name    VARCHAR(32) NOT NULL,
    series_id       VARCHAR(32) NOT NULL,
    series_name     VARCHAR(256),
    year            INTEGER     NOT NULL,
    period          VARCHAR(4)  NOT NULL,
    period_name     VARCHAR(16),
    date            VARCHAR(10) NOT NULL,
    value           DOUBLE PRECISION,
    footnotes       JSONB,
    latest          BOOLEAN     NOT NULL DEFAULT FALSE,
    fetched_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    raw_json        JSONB,

    CONSTRAINT uq_bls_ppi_data_point
        UNIQUE (source, dataset_name, series_id, date)
);

CREATE INDEX ix_bls_ppi_series_date ON bls_ppi_observations (series_id, date);
CREATE INDEX ix_bls_ppi_date        ON bls_ppi_observations (date);
CREATE INDEX ix_bls_ppi_latest      ON bls_ppi_observations (latest) WHERE latest = TRUE;
CREATE INDEX ix_bls_ppi_fetched_at   ON bls_ppi_observations (fetched_at);
```

---

## 7. 次にモデル追加・migrationへ進む場合の注意点

- **モデルクラス**: `db/models.py` に `BLSPPIObservation` を追加。
- **Alembic**: `UUID` や `JSONB` の扱いは既存の `RawItem` や `AlertLog` のパターンを踏襲する。
- **SQLite 互換**: ローカル開発用の SQLite では `JSONB` を `Text` (JSON) として扱うように SQLAlchemy の型定義で吸収する。
- **独立性**: 他のテーブルへの影響は一切ないが、クエリ層 (`bls_ppi_query.py`) では `date` 文字列のパース処理が必要になる。
