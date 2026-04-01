# マップ描画の最終復旧計画：座標データの階層化対応

実機検証の結果、一部のアラートデータにおいて座標（Lat/Lng）がトップレベルではなく、`metadata_json` または `cascading_impacts` 内にのみ格納されていることが判明しました。これにより描画ロジックがスキップされていた問題を、データのフォールバック処理によって完全に解消します。

## User Review Required

> [!IMPORTANT]
> 座標データの参照順序を以下の通り「階層化」します：
> 1.  トップレベル (`alert.location_lat`)
> 2.  メタデータ内 (`alert.metadata_json.location_lat`)
> 3.  波及効果データの初動地点 (`alert.cascading_impacts[0].location_lat`)
> 
> これにより、データの不備にかかわらず、可能な限り地図上へのプロットと `flyTo` を実行します。

---

## 提案される変更 (Proposed Changes)

### 1. 座標取得関数の導入 (`render.ts`)
*   `getAlertCoords(alert)` 関数を新設し、トップレベル・メタデータ・波及効果の順に有効な座標を探索します。
*   この関数を `L.marker` および `flyTo` の両方で利用します。

### 2. ループ内ロジックの修正
*   `if (alert.location_lat && alert.location_lng)` という厳格なチェックを、`getAlertCoords` の結果に基づくチェックに緩和します。
*   アーク描画のソース座標（Start点）も、同様のロジックで取得するように修正します。

### 3. デバッグログの追加
*   `[Antigravity] Found Coordinates via: {Source}` (Normal, Metadata, or Impacts) を追加し、どの階層からデータを取得したかを明示します。

### 4. 実行タイミングの再調整
*   `setTimeout` の値を 300ms 程度に微増させ、アセット（Leafletの初期化）の完了をより確実に待ちます。

---

## Verification Plan

### Automated Verification (Browser Tool)
1.  `npm run build` を実行。
2.  ブラウザツールで再度 `http://localhost:5173/` を開き、フィードのアイテムをクリック。
3.  **座標の取得元がログに記録されること**、および **マップが正しく移動してパルスが表示されること** を確認。
4.  スクリーンショットにより、赤いパルスの存在を証明。
