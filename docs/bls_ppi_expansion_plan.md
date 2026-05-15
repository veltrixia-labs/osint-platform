# BLS PPI Integration — Expansion Plan

## 概要

BLS (Bureau of Labor Statistics) の PPI (Producer Price Index: 生産者物価指数) データを OSINT プラットフォームに統合するための計画。
BEA の実質・名目成長率データに加え、PPI を取り入れることで、産業別の価格圧力（コスト増）、マージン圧迫、およびインフレ波及経路を定量的に分析可能にする。

---

## 1. 取得Series一覧と用途

| Series ID | Series Name | 用途 | BEA GDPbyIndustry 対応候補 |
|-----------|-------------|------|---------------------------|
| **WPUFD4** | PPI Final demand | マクロ経済の総合的な卸売価格圧力の把握 | GDP (Total) |
| **WPUFD49104** | Final demand goods | 財（Goods）セクターのインフレ傾向 | Manufacturing (31G) |
| **WPUFD49207** | Final demand services | サービスセクターの価格圧力 | Services (PSERV) |
| **WPU057** | Fuels and related products | エネルギーコストの上昇圧力 | Utilities (22), Transportation (48TW) |
| **WPU101** | Iron and steel | 金属・原材料コスト | Construction (23), Manufacturing (31G) |
| **WPU081** | Lumber and wood products | 住宅・建築資材コスト | Construction (23), Real estate (53) |
| **WPU114** | Machinery and equipment | 設備投資コスト | Capital Goods, Manufacturing (31G) |
| **WPU117** | Electronic components | 半導体・電子部品価格 | Information (51), Manufacturing (31G) |

---

## 2. Pro 分析での活用方法

- **価格転嫁分析**: 
    - `PPI (WPUFD49104)` の上昇と、`BEA GDPbyIndustry (Manufacturing)` の名目付加価値の変化を比較し、コスト増が収益を圧迫しているか、あるいは価格転嫁に成功しているかを分析。
- **実質成長の検証**:
    - NIPA の名目 GDP 成長率に対し、PPI の上昇率を差し引くことで、物価変動を除いた産業別の「実質的な勢い」を独自に推計（BEA 実質値の補完）。
- **先行指標としての利用**:
    - エネルギー (`WPU057`) や原材料 (`WPU101`) の PPI 上昇を、数四半期後の関連産業（建設・運輸）の成長鈍化リスクとして提示。

---

## 3. Expert 分析での活用方法

- **ニュースとの紐付け**:
    - 例：「中東情勢の緊迫化」という RSS アラートに対し、`WPU057 (Fuels)` の直近の上昇トレンドを組み合わせ、「燃料コスト増が航空・運輸セクターの利益率を毀損する可能性が高い」と LLM が推論。
- **企業業績へのインパクト予測**:
    - 半導体不足や価格高騰 (`WPU117`) のデータを、テック企業や自動車メーカーの決算期待値の修正理由として活用。

---

## 4. 今後の実装ステップ

1. **DB設計**: `bls_ppi_observations` テーブルの作成（NIPA と同様の時系列構造）。
2. **正規化**: BLS API の Month/Year 構造を `time_period` (YYYY-MM) に変換。
3. **リポジトリ**: Upsert ロジックの実装。
4. **統合クエリ**: BEA 産業コードと PPI Series ID をマッピングする連想テーブルの導入、またはクエリ層での紐付け。
5. **定期ジョブ**: 毎月の発表日に合わせた自動取得ジョブの追加。

---

## 5. API 制限と注意点

- **登録キー (Registration Key)**:
    - キーなし: 1日10クエリ、1クエリあたり最大50シリーズ、過去10年まで。
    - キーあり: 1日500クエリ、1クエリあたり最大50シリーズ、過去20年まで。
- **更新頻度**:
    - PPI は通常、毎月の中旬（10日〜15日頃）に前月分が発表される。取得ジョブはこのスケジュールに同期させる必要がある。
