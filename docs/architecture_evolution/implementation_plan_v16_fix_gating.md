# マップ描画の修正とカメラ遷移の独立化計画

ブラウザでの検証結果、カメラ遷移（flyTo）と描画ロジックが特定の条件（cascading_impactsの有無）に阻害されていることが判明しました。これを解消し、確実に描画されるように修正します。

## User Review Required

> [!IMPORTANT]
> これまでカメラの移動（flyTo）がアーク描画（cascading_impacts）の有無に依存していましたが、これを完全に分離します。これにより、波及効果データがないアラートでも正しくズームされるようになります。

---

## 提案される変更 (Proposed Changes)

### 1. カメラ遷移 (flyTo) の独立化 (`render.ts`)
*   `if (alert.cascading_impacts)` の外側に `flyTo` ロジックを移動します。
*   アラートに座標があれば、パルス描画と同時にカメラ移動を開始するようにします。

### 2. データ参照の冗長化
*   波及効果データの参照を `alert.cascading_impacts || alert.metadata_json?.cascading_impacts` に拡張し、APIのレスポンス形式の差異を吸収します。

### 3. デバッグログの強化
*   `[Antigravity] Marker Created...` のログが出力されない原因を調査するため、座標チェック前にもログを挟みます。
*   アーク描画の開始・終了時にも詳細なログを追加します。

### 4. zIndexOffset の適用範囲拡大
*   全てのマーカー（アラート、レポート、波及ノード）に対して `zIndexOffset: 1000` を適用し、タイルレイヤーとの重なり問題を恒久的に解決します。

---

## Verification Plan

### Automated Verification (Browser Tool)
1.  `npm run build` を実行。
2.  ブラウザツールで `http://localhost:5173/` を開き、フィードのアイテムをクリック。
3.  **カメラが移動すること**、**赤いパルスが表示されること**、**アークが描画されること**（データがある場合）を視覚的に確認。
4.  コンソールログに `Starting Transition to...` が確実に出力されているか確認。
