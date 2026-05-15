# BEA GDP by Industry — Storage Design

## 概要

BEA API から取得した GDP by Industry データをDBに格納するためのテーブル設計。
将来的に複数年・四半期・複数 TableID への拡張、および重複取得時の安全な UPSERT を想定する。

---

## 1. テーブル設計

### テーブル名: `bea_gdp_by_industry`

| # | カラム名 | 型 | NOT NULL | 説明 |
|---|---------|------|----------|------|
| 1 | `id` | UUID | ✅ | PK. `uuid4()` auto-generated |
| 2 | `dataset_name` | String(64) | ✅ | BEA dataset 識別子 (e.g. `"GDPbyIndustry"`) |
| 3 | `table_id` | String(16) | ✅ | BEA Table ID (e.g. `"1"`, `"5"`, `"25"`) |
| 4 | `frequency` | String(4) | ✅ | `"A"` (Annual) / `"Q"` (Quarterly) |
| 5 | `year` | String(8) | ✅ | `"2022"`, `"2023"` 等 |
| 6 | `quarter` | String(8) | ✅ | 年次データ: `"2022"` / 四半期: `"2022Q1"` 等 |
| 7 | `industry` | String(16) | ✅ | BEA Industry code (e.g. `"11"`, `"3361MV"`) |
| 8 | `industry_description` | String(256) | ❌ | Industry 名称 (補足情報) |
| 9 | `data_value` | Float | ❌ | 数値データ。変換不可時は `NULL` |
| 10 | `note_ref` | String(32) | ❌ | BEA NoteRef (e.g. `"1"`, `"1;1.1.A"`) |
| 11 | `note_text` | Text | ❌ | NoteRef を解決したテキスト |
| 12 | `statistic` | String(128) | ❌ | BEA Statistic フィールド |
| 13 | `utc_production_time` | String(32) | ❌ | BEA レスポンスの生成日時 (文字列保持) |
| 14 | `fetched_at` | DateTime(tz) | ✅ | データ取得日時。`server_default=func.now()` |
| 15 | `raw_json` | JSON | ❌ | 元の行データ (デバッグ・監査用) |

---

## 2. 型の選定理由

### `year`: String vs Integer

**→ String(8) を採用**

| 候補 | 利点 | 欠点 |
|------|------|------|
| Integer | ソート・比較が自然 | BEA API が文字列で返すため変換が必要。将来 `"ALL"` 等の特殊値に非対応 |
| String | BEA レスポンスをそのまま格納。特殊値にも対応可 | 範囲検索時にキャスト不要だが辞書順ソートになる（4桁年なら問題なし） |

BEA API が `"Year": "2022"` と文字列で返すこと、および `Year=ALL` でリクエストする場合もあり得ることから、String で統一する。
4桁の年であれば辞書順ソート = 時系列ソートとなるため実害なし。

### `quarter`: String

BEA レスポンスでは年次データで `"Quarter": "2022"`、四半期データでは `"Quarter": "2022Q1"` のように返される。
形式が一定でないため String で受ける。

### `data_value`: Float vs Numeric

**→ Float を採用**

| 候補 | 利点 | 欠点 |
|------|------|------|
| Float | SQLAlchemy の既存モデルと統一。SQLite 互換 | 浮動小数点丸め誤差 (BEA データは小数第1位まで → 実害なし) |
| Numeric(precision, scale) | 正確な10進数 | SQLite では `NUMERIC` affinity で実質 REAL 扱い。PostgreSQL でも BEA の表示精度(小数1桁)に対してオーバースペック |

既存モデル (`Float` 統一) との一貫性、および SQLite/PostgreSQL 両対応を考慮して Float を採用。
BEA データは小数第1位（Billions of dollars）なので丸め誤差は問題にならない。

### `utc_production_time`: String vs DateTime

**→ String(32) を採用**

BEA API が返す `"2026-05-04T04:07:58.600"` はタイムゾーン情報を含まない独自フォーマット。
無理に DateTime にパースするより、原値を保持した方がデバッグ性・トレーサビリティが高い。

### `raw_json`: JSON

元の行データ (`{"TableID": "1", "Frequency": "A", ...}`) を格納する。

> [!WARNING]
> **肥大化リスク**: 100行/年/TableID × 複数年 × 複数テーブルで増加する。
> 初期段階では監査・デバッグ用に保持するが、本番運用で件数が膨らんだ場合は
> バッチで古い `raw_json` を NULL 化するか、別テーブルに分離する運用が推奨される。
> 目安: GDPbyIndustry Table1 の1年分 = 約100行 × ~400B/行 ≈ 40KB → 10年分でも ~400KB。
> 実害が出るのは複数 TableID を大量取得するフェーズ以降。

---

## 3. Notes を同一テーブルに持つか

**→ 同一テーブルに `note_ref` + `note_text` を持つ（正規化済みテキストを展開格納）**

| 方式 | 利点 | 欠点 |
|------|------|------|
| 別テーブル (`bea_notes`) | 正規化。テキスト重複なし | JOIN が必要。Notes は数件/レスポンスで重複コスト極小 |
| 同一テーブル展開 | JOINなしでクエリ可能。シンプル | テキスト重複 (同一 note_text が100行に展開される) |

**採用理由**: 
- Notes はレスポンスあたり最大5件程度、テキスト長も最大300文字程度
- 100行 × 300B = 30KB/レスポンス の重複 → 実害なし
- 分析クエリの大半が `data_value` と `note_text` を同時参照するため、JOINなしの方が実用的
- 将来の別テーブル分離は容易（`note_ref` をキーに JOIN するだけ）

---

## 4. UNIQUE 制約

```sql
UNIQUE (dataset_name, table_id, frequency, year, quarter, industry)
```

**制約名**: `uq_bea_gdp_data_point`

### 理由

BEA API において、同一の (dataset, table, frequency, year, quarter, industry) の組み合わせは
一意のデータポイントを表す。同じパラメータで再取得した場合に重複行が発生しないよう、
この6カラムに UNIQUE 制約を設定する。

これにより:
- **UPSERT (INSERT ... ON CONFLICT UPDATE)** で安全に再取得・更新が可能
- 同じ年のデータを繰り返し取得しても行が膨張しない
- `data_value` が BEA 側で改定された場合、UPDATE で反映される

### quarter を含める理由

年次データでは `quarter = "2022"` で固定だが、四半期データでは `quarter = "2022Q1"` 等に分かれる。
同一年の年次データと四半期データが共存する場合を区別するために `quarter` を含める。

---

## 5. Index 設計

| Index 名 | カラム | 種別 | 用途 |
|----------|--------|------|------|
| `uq_bea_gdp_data_point` | `(dataset_name, table_id, frequency, year, quarter, industry)` | UNIQUE | 重複防止 + UPSERT キー |
| `ix_bea_gdp_year_industry` | `(year, industry)` | B-tree | 「特定年の特定産業」検索。時系列比較クエリの高速化 |
| `ix_bea_gdp_fetched_at` | `(fetched_at)` | B-tree | 「直近取得分」のフィルタリング。鮮度管理 |

### Index 設計の理由

1. **UNIQUE index** — UPSERT の ON CONFLICT 判定に必須。これが主要な検索パスにもなる
2. **year + industry** — 最も頻出する分析パターンは「ある産業の年次推移」と「ある年の産業横断比較」。この複合インデックスで両方カバーできる
3. **fetched_at** — データの鮮度管理（「最新取得分のみ表示」「N日以上前のデータを再取得」）に使用

> [!NOTE]
> 初期段階（数百〜数千行）では index の効果は限定的だが、複数年×複数 TableID に拡張した場合に効いてくる。
> コストは INSERT 時の微小なオーバーヘッドのみ。

---

## 6. 推奨 DDL

### PostgreSQL

```sql
CREATE TABLE bea_gdp_by_industry (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    dataset_name    VARCHAR(64) NOT NULL,
    table_id        VARCHAR(16) NOT NULL,
    frequency       VARCHAR(4)  NOT NULL,
    year            VARCHAR(8)  NOT NULL,
    quarter         VARCHAR(8)  NOT NULL,
    industry        VARCHAR(16) NOT NULL,
    industry_description VARCHAR(256),
    data_value      DOUBLE PRECISION,
    note_ref        VARCHAR(32),
    note_text       TEXT,
    statistic       VARCHAR(128),
    utc_production_time VARCHAR(32),
    fetched_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    raw_json        JSONB,

    CONSTRAINT uq_bea_gdp_data_point
        UNIQUE (dataset_name, table_id, frequency, year, quarter, industry)
);

CREATE INDEX ix_bea_gdp_year_industry ON bea_gdp_by_industry (year, industry);
CREATE INDEX ix_bea_gdp_fetched_at    ON bea_gdp_by_industry (fetched_at);
```

### SQLite (ローカル開発用)

```sql
CREATE TABLE bea_gdp_by_industry (
    id              TEXT        PRIMARY KEY,
    dataset_name    TEXT        NOT NULL,
    table_id        TEXT        NOT NULL,
    frequency       TEXT        NOT NULL,
    year            TEXT        NOT NULL,
    quarter         TEXT        NOT NULL,
    industry        TEXT        NOT NULL,
    industry_description TEXT,
    data_value      REAL,
    note_ref        TEXT,
    note_text       TEXT,
    statistic       TEXT,
    utc_production_time TEXT,
    fetched_at      TEXT        NOT NULL DEFAULT (datetime('now')),
    raw_json        TEXT,

    UNIQUE (dataset_name, table_id, frequency, year, quarter, industry)
);

CREATE INDEX ix_bea_gdp_year_industry ON bea_gdp_by_industry (year, industry);
CREATE INDEX ix_bea_gdp_fetched_at    ON bea_gdp_by_industry (fetched_at);
```

---

## 7. SQLAlchemy Model 案

```python
class BeaGdpByIndustry(Base):
    __tablename__ = "bea_gdp_by_industry"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    dataset_name = Column(String(64), nullable=False)
    table_id = Column(String(16), nullable=False)
    frequency = Column(String(4), nullable=False)
    year = Column(String(8), nullable=False)
    quarter = Column(String(8), nullable=False)
    industry = Column(String(16), nullable=False)
    industry_description = Column(String(256))
    data_value = Column(Float)
    note_ref = Column(String(32))
    note_text = Column(Text)
    statistic = Column(String(128))
    utc_production_time = Column(String(32))
    fetched_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    raw_json = Column(JSON)

    __table_args__ = (
        UniqueConstraint(
            "dataset_name", "table_id", "frequency",
            "year", "quarter", "industry",
            name="uq_bea_gdp_data_point"
        ),
        Index("ix_bea_gdp_year_industry", "year", "industry"),
        Index("ix_bea_gdp_fetched_at", "fetched_at"),
    )
```

---

## 8. DB 保存実装へ進む場合の注意点

### 8.1 Alembic マイグレーション

- `db/models.py` にモデルを追加した後、`alembic revision --autogenerate -m "add_bea_gdp_by_industry"` でマイグレーションを生成
- 既存モデルの `env.py` は `from db.models import Base` を参照済みなので、モデル追加だけで autogenerate が効く
- **SQLite 制約**: SQLite は `ALTER TABLE ADD CONSTRAINT` を完全にはサポートしないため、UNIQUE 制約は `batch_alter_table` が必要になる場合がある。ただし新規テーブルなら `CREATE TABLE` に含まれるため問題なし

### 8.2 UPSERT 戦略

```python
# PostgreSQL の場合
from sqlalchemy.dialects.postgresql import insert as pg_insert

stmt = pg_insert(BeaGdpByIndustry).values(rows)
stmt = stmt.on_conflict_do_update(
    constraint="uq_bea_gdp_data_point",
    set_={
        "data_value": stmt.excluded.data_value,
        "industry_description": stmt.excluded.industry_description,
        "note_ref": stmt.excluded.note_ref,
        "note_text": stmt.excluded.note_text,
        "statistic": stmt.excluded.statistic,
        "utc_production_time": stmt.excluded.utc_production_time,
        "fetched_at": func.now(),
        "raw_json": stmt.excluded.raw_json,
    }
)
```

- SQLite の場合は `INSERT OR REPLACE` または個別の `merge` ロジックが必要
- 本プロジェクトの `DATABASE_URL` 設定に応じて分岐するか、SQLAlchemy Core の dialect-aware な書き方を検討

### 8.3 既存システムへの影響

- `bea_gdp_by_industry` は完全に独立したテーブルで、既存テーブルとの FK は持たない
- Free Alert Feed / Context Briefs のコードパスには一切影響しない
- `main.py` のスケジューラに BEA fetch ジョブを追加する場合は別フェーズとする

### 8.4 raw_json の格納内容

正規化前の**行単位**の dict を格納する（レスポンス全体ではない）。

```json
{
  "TableID": "1",
  "Frequency": "A",
  "Year": "2022",
  "Quarter": "2022",
  "Industry": "11",
  "IndustrYDescription": "Agriculture, forestry, fishing, and hunting",
  "DataValue": "294.0",
  "NoteRef": "1"
}
```

レスポンス全体の保存が必要な場合は、`raw_items` テーブルの既存パターン（`payload_json` + `payload_hash`）を流用することも可能。

---

## 9. 想定データ規模

| パラメータ | 値 | 行数/回 |
|-----------|-----|---------|
| TableID=1, Year=2022, Freq=A | 1年 × 年次 | ~100 行 |
| TableID=1, Year=ALL, Freq=A | 全年 × 年次 (1997-2024) | ~2,800 行 |
| TableID=1, Year=ALL, Freq=Q | 全年 × 四半期 | ~11,200 行 |
| 全 TableID (1-25) × Year=ALL × Freq=A | 全テーブル × 全年 | ~70,000 行 |

初期段階は数百行。全量取得しても10万行未満の小規模テーブル。
