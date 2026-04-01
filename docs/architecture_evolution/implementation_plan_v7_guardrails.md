# Reliability & Stability Guardrails (Phase 4.5)

この計画では、自律稼働を開始した「第2次波及エンジン」の信頼性と持続可能性を高めるためのガードレールを実装します。

## Proposed Changes

### 1. Learning Loop: 過学習防止 (Overlearning Prevention)
`learning_loop.py` に以下の数理的な制約を追加します。

*   **Correction Clipping**: 1回の更新で変更できる重みの最大幅を制限（例: ±0.05）。極端な変動（ブラックスワン）によるグラフの崩壊を防ぎます。
*   **Outlier Rejection**: 市場の変動幅が過去の標準偏差を大幅に超える場合、そのデータポイントを「ノイズ」として更新をスキップします。

#### [MODIFY] [learning_loop.py](file:///c:/RDTP project/Development/OSINT_analytics/jobs/learning_loop.py)

### 2. Discovery Engine: LLM リミット対策 (Token Preservation)
`impact_discovery.py` に以下の効率化レイヤーを追加します。

*   **Identity Cache**: すでに一度抽出したエンティティの座標やメタデータをキャッシュし、2回目以降はLLMに聞かずにDB/Cacheから参照します。
*   **Signal Tiering**: 重要度の低い警報（Watch等）ではディスカバリーをスキップし、Critical/Elevatedな高精度信号のみにAPIリソースを集中させます。
*   **Batch Requesting**: 個別のニュースごとではなく、一定時間内のニュースをまとめて1回のLLMコールで処理するオプションを検討します。

#### [MODIFY] [impact_discovery.py](file:///c:/RDTP project/Development/OSINT_analytics/processor/impact_discovery.py)
#### [MODIFY] [alert_manager.py](file:///c:/RDTP project/Development/OSINT_analytics/jobs/alert_manager.py)

## Verification Plan

### Automated Tests
*   `test_learning_clipping.py`: 極端な（例: +50%）の変動を与えても、重みが一定範囲（±0.05）に収まることを確認。
*   `test_discovery_cache.py`: 同じ内容の2回目のリクエストでLLM呼び出しが発生しないことをモックで確認。
