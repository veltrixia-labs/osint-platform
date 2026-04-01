# 波及効果エンジンの「幾何学的アップグレード」実装計画

この計画では、3次波及までの連鎖（Cascading Logic）を、直線ではなく「幾何学的に計算されたベジェ曲線」によって視覚化し、プロフェッショナルなインテリジェンス・ダッシュボードとしての完成度を極限まで高めます。

## User Review Required

> [!IMPORTANT]
> **ベジェ曲線の視覚的階層化**
> *   **1次（実線・太）➔ 2次（細・半透明）➔ 3次（点線・極細）** と、影響が遠ざかるにつれて描画を減衰させます。
> *   波及強度（Intensity）と Alpha値（予測変動率）をアニメーションの「速度」に同期させ、システムが生きているかのような「呼吸」を表現します。

---

## 提案される変更 (Proposed Changes)

### 1. ベジェ曲線生成エンジンの実装 (`render.ts`)
*   **`getBezierPath(start, end, level, index)`**: 
    *   2地点間の中点から、距離の 20-30% の垂線方向オフセットを計算。
    *   同一地点から複数のアークが出る場合、`index` に基づいてオフセット量を調整し、重なりを回避。
    *   Webメルカトル図法上の歪みを考慮した、滑らかな座標点リスト（32ステップ以上）を生成。

### 2. 再帰的描画ロジックの統合 (`render.ts`)
*   **`renderImpactChain(parentCoords, impacts, level)`**:
    *   再帰深度（最大3）に基づいて `getBezierPath` のスタイルを変更。
    *   **Level 1**: `weight: 3`, `opacity: 1.0`, `solid line`.
    *   **Level 2**: `weight: 1.5`, `opacity: 0.7`, `dashed line`.
    *   **Level 3**: `weight: 1.0`, `opacity: 0.4`, `faded dashed line`.

### 3. 曲線同期型粒子アニメーション
*   `requestAnimationFrame` 内の補間計算を、直線の `lerp` から、生成された `bezierPoints` 配列のインデックス追従型に変更。
*   **速度の同期**: `durationMs = baseline / (intensity * abs(alpha))`. 強力なインパクトほど粒子が高速に流れます。

### 4. アルファ・インジケーターの刷新
*   ノードラベルに「Predicted Alpha: ±X.X%」を明示。
*   モックアップ（ Silicon Valley ➔ Taiwan ➔ Tokyo ）に忠実な、深みのあるダークブルー/エメラルド/クリムゾンのカラーパレットを採用。

---

## Verification Plan

### Manual Verification
1.  **階層描画の確認**: 地図をズームアウトし、アークが重ならずに美しく分散して、3段階先まで伸びているか確認。
2.  **アニメーションの滑らかさ**: 粒子がカクつかずに曲線上を正確に移動しているか。
3.  **ティア別挙動**: Freeティアで2次以降にブラーがかかっているか。
