# 領域分離型（Block-Layout）アーキテクチャへの再構築計画

先日実装した「全画面マップオーバーレイ（透過レイヤー）アーキテクチャ」における透過計算・イベント制御の煩雑さとUX阻害を鑑み、ユーザー指示に基づき確実性の高い**標準的なディスプレイ切り替え（`display: block / none`）アーキテクチャに差し戻し再構築**します。

ただし、マップの再描画負荷を防ぐための「永続レイヤー設計（`currentDynamicLayer`）」や「アークアニメーション（`requestAnimationFrame`）」といった描画エンジンの最適化部分は維持統合します。

---

## 提案される変更 (Proposed Changes)

### 1. CSSオーバーレイ・透過処理の完全撤廃 (`style.css`)
ガラスモーフィズム等の影響で発生していたクリック干渉を根本から除去します。

#### [MODIFY] `web_dashboard/src/style.css`
*   **削除**:
    *   `.mode-obscure` クラスの全定義。
    *   `.main-content`, `#alerts-container` に対する `pointer-events: none` および子要素への `pointer-events: auto !important` のハック。
    *   `#map-page-container` の `position: fixed; inset: 0; z-index: 0;`。
*   **復元**:
    *   `.app-container` や `.main-content` を一般的なグリッド/フレックスフローの定義に簡略化。
    *   `.sidebar` 等の背景を少し濃いダークに戻し、視認性を最優先にする。

### 2. DOM構造の差し戻しとライフサイクル (`main.ts`)
マップレイヤーを「背景固定」から「メインコンテンツ内の1パネル」へ戻します。

#### [MODIFY] `web_dashboard/src/main.ts`
*   **HTML構造**: `div#map-page-container` を `.app-container` の最後尾から `.main-content` の内部へ戻します。
*   **タブ切り替え (`handleTabSwitch`)**:
    *   透過制御 (`.mode-obscure` 等) のロジックを削除。
    *   `feedContainer`, `mapContainer`, `liveFeed` に対して厳格に `display: 'none'` と `display: 'block'` を切り替える基本ロジックを復元。
*   **アーク描画イベント (`focus-map`)**:
    *   フィード内で監視・描画する状態から、「マップ画面へ遷移 (`currentTab = 'map'`) してからキャンバスにアークを描画する」フローに変更。

### 3. マップ描画エンジンの維持 (`render.ts`)
Leaflet 特有の非表示（`display: none`）復帰時のバグ対策を施します。

#### [MODIFY] `web_dashboard/src/modules/render.ts`
*   前回追加した `currentDynamicLayer` の常駐機能は残し、初期化負荷を下げます。
*   タブ切り替え等でマップが `display: block` に復帰した際、コンテナサイズを再取得するために `setTimeout` 等で `map.invalidateSize()` を確実に実行し、タイルが半分切れる Leaflet バグを防止します。

---

## User Review Required

> [!IMPORTANT]
> 透過・オーバーレイ化を完全に廃止し、タブや機能ごとに「画面がカチッと切り替わる」質実剛健なダッシュボードスタイルへ原点回帰します。
> 
> *   **利点**: 誤操作（クリック貫通や意図せぬマップドラッグ等）が100%発生せず、レポート画面などの長文ドキュメントが最も読みやすくなります。
> *   **動作**: Feed のカード（Strategic AI Infrastructure Surge 等）をクリックすると、一瞬で「Global Map 画面」に切り替わり、マップ上で光の粒が流れるアークが描画されます。
>
> この堅牢なアーキテクチャへの回帰計画にて、実装を進めてよろしいでしょうか？

## Verification Plan

### Manual Verification
1.  **タブ切り替え**: Intelligence Feed, Global Map, Expert Reports, Subscription Plans を切り替えた際、それぞれの専用画面が完全に独立して表示され、背景にマップが透けないこと。
2.  **イベント・クリック**: Feed画面で自由にカードを選択・クリックできること。（背後のマップを操作できてしまうバグが消えていること）。
3.  **アーク描画バインド**: Feedのカードをクリックすると自動的にGlobal Mapタブに切り替わり、前回実装したパルスアニメーション付きの曲線アークが描画されること。
