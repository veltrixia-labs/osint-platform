# 全画面マップコンポーネントのZ-Indexレイヤーアーキテクチャへの完全移行

現在の「画面の相互切り替え（display:none/block）」アーキテクチャから、**「グローバルマップを常に最背面に描画し、機能コンポーネントを前面のレイヤー（半透過のガラスモーフィズム）として重ねる」**本格的なオーバーレイアーキテクチャへとUI/UXを刷新します。

## 課題の背景と目的
これまでのダッシュボードは `Feed` や `Map` が同じドキュメントフロー内で `display: block / none` によって切り替わっており、マップのチラツキや再レンダリングによるパフォーマンス低下、レイアウトの出血（はみ出し）が発生していました。
本改修により、**マップコンポーネントを永続的（Lifecycle-Persistent）な背景**として稼働させ、クリックイベントに反応して即座にアークを描画する真の「Command Center」体験を実現します。

---

## 提案される変更 (Proposed Changes)

### 1. CSS アーキテクチャのオーバーレイ化 (style.css)
*マップを最背面に、それ以外を透過レイヤーとして浮かせる*

#### [MODIFY] `web_dashboard/src/style.css`
*   `#map-page-container` を `position: fixed; inset: 0; z-index: 0;` のフルスクリーンコンテナに変更。
*   `.app-container` および中央の `.main-content` サイドバー `.sidebar` 等に適切な `z-index` (例: 10以上) と `backdrop-filter: blur(...)` を適用。
*   状態クラス（例: `.mode-obscure`）を追加し、サブスクリプションやレポート画面へ遷移した際に、中央メインコンテンツの背景を更に濃く・強くぼかして、マップを隠す表現を実装。

### 2. マップアーキテクチャとアークエンジンの常駐化 (render.ts)
*マップを再生成せず、イベントに応じてデータレイヤーだけを更新する*

#### [MODIFY] `web_dashboard/src/modules/render.ts`
*   **`initBackgroundMap(container)`関数**: ログインと同時に背後でマップを初期化。ベースレイヤーのみを描画し、使い回す。
*   **`updateMapFocus(alert, alertsList)`関数**: 
    *   呼び出されるたびに「古いアーク・マーカー」をレイヤーグループ（`L.layerGroup`）からクリア。
    *   選択された Specific Alert の座標へ `map.flyTo()` もしくは `panTo()` で滑らかに移動。
    *   既存のLeaflet Polylineを用いて、曲線アークとパルスアニメーションを描画。
    *   要件通り `console.log("[Antigravity] Arc Triggered: From {coords} to {coords}")` を出力。

### 3. イベントバスとライフサイクル制御 (main.ts)
*画面遷移時の中央コンテナ制御とイベントディスパッチ*

#### [MODIFY] `web_dashboard/src/main.ts`
*   初期化処理 (`initDashboard`) 内で `renderMapPage()` 相当の処理を呼び出し、背景にマップを起動。
*   `handleTabSwitch` 内で、選択されたタブに応じて `.main-content` の `.mode-obscure` (ぼかし・暗転) クラスを着脱。不要なコンテナは非表示にするが、マップ自体は常に稼働。
*   要件通り `console.log("[Antigravity] Viewport State: {active_tab}")` を出力。
*   `focus-map` イベントのペイロードを強化し、遷移ではなくバックグラウンドの `updateMapFocus()` へ直接信号を送り、カメラとアークだけを更新。

---

## User Review Required

> [!IMPORTANT]
> この変更はフロントエンドの骨組み（DOM構造とCSSスタッキングコンテキスト）を根本的に変更します。
> 既存の `index.html` および `style.css` で定義されているレイアウト構造に対して強引に `fixed` を適用するため、モバイルビュー（スマホ表示）における一部のスクロール体験などが影響を受ける可能性があります。
> 「デスクトップ環境におけるプロフェッショナルな情報ダッシュボード」に焦点を当ててレイアウト調整・Z-index構成を進めてよろしいでしょうか？

## Verification Plan

### Manual Verification
1.  ログイン後、全体の背後にグローバルマップが表示されていること。
2.  フィードから特定のアラートをクリックすると、画面はフィードのまま背後のマップがスムーズにPan移動し、「そのアラートのアーク」だけが描画されること。
3.  サイドバーから「Subscription Plans」をクリックすると、中央のフィードが非表示になり、背後のマップが強いブラー処理で覆い隠されること。
4.  ブラウザのコンソール（F12）に `[Antigravity] Arc Triggered: From {...} to {...}` と `[Antigravity] Viewport State: ...` が正しく記録されること。
