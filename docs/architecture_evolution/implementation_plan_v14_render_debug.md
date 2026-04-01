# マップ描画エンジンの緊急デバッグと安定化計画

ユーザーから報告された「マーカー非表示」「アーク描画の不発」を解決するため、描画ライフサイクルの同期制御と、詳細なデバッグログの実装を行います。

## User Review Required

> [!IMPORTANT]
> この修正により、タブ切り替えと描画の「競合状態（Race Condition）」を排除します。具体的には、画面が完全に `display: block` になったことを確認してから、100msの待機時間を挟んで描画を開始するように変更します。
> 
> *   描画が少し（合計150ms程度）遅延して見える可能性がありますが、描画の確実性は大幅に向上します。

---

## 提案される変更 (Proposed Changes)

### 1. タブ切り替えと描画の同期化 (`main.ts`)
#### [MODIFY] `web_dashboard/src/main.ts`
*   `handleTabSwitch` の引数を拡張し、`focusAlertId?: string` を受け取れるようにします。
*   `focus-map` イベント発火時に、`renderMap` を直接呼ばず、`handleTabSwitch('map', alertId)` を経由するように変更します。これにより、マップコンテナの表示（`display: block`）と描画の順序を保証します。

### 2. 描画エンジンの堅牢化と強制ログ (`render.ts`)
#### [MODIFY] `web_dashboard/src/modules/render.ts`
*   **安全待機**: `renderMap` の冒頭に `await new Promise(r => setTimeout(r, 100))` を追加し、Leafletがコンテナサイズを正しく認識できる猶予を与えます。
*   **レイヤーバインド再定義**: `currentDynamicLayer` が確実に `currentGlobalMap` に `addTo` されていることをチェックし、無ければ再バインドします。
*   **強制ログ実装**:
    *   `[Antigravity] Marker Created at: {coords} with Intensity: {intensity}`
    *   `[Antigravity] Arc Layer Active: {true/false}`
    *   `[Antigravity] Mapping Alert` も継続して出力。

### 3. CSS/HTMLの再確認
*   `style.css` の `@keyframes pulse-ring` が正しく閉じられているか、スペルミスがないか再度精査します。

---

## 期待される結果

1.  **視認性**: フィードからアラートを選択した際、確実に赤いパルスとアークが表示される。 
2.  **追跡性**: 開発者コンソールを開くだけで、データが地図上に正しくプロットされたか、どの地点への遷移が開始されたかが一目暸然になる。

---

## Verification Plan

### Manual Verification
1.  **タブ切り替えテスト**: 各タブを往復した後、「Global Map」が正しく再描画されるか確認。
2.  **アラート連動テスト**: Feed画面で「Strategic AI...」をクリックし、1.8秒の flyTo 完了後にアークが伸び、パルスリングが消えていないことを確認。
3.  **コンソールログ確認**: 指定された `[Antigravity]` プレフィックスのログがすべて出力されていることを確認。
