# 第2次波及効果（Second-Order Impact）エンジンの完全復旧計画

この計画では、OSINT Command Center の空間インテリジェンス機能を拡張し、アラートが特定のステークホルダーやサプライチェーンに与える「2次的な影響」を視覚化します。

## User Review Required

> [!IMPORTANT]
> 波及効果の視覚化には、ユーザーのサブスクリプションティアに応じた制限（Gating）を物理的に適用します。
> *   **Freeティア**: 2次波及以降は「Ghost Nodes」として表示され、詳細データは秘匿されます。
> *   **Pro/Expertティア**: 全てのノードと予測変動率（Alpha）がフルカラーで表示されます。

---

## 提案される変更 (Proposed Changes)

### 1. 座標取得ロジックの汎用化 (`render.ts`)
*   `getAlertCoords` を拡張、または `getNodeCoords` を新設し、ステークホルダーノードの座標を `location_lat/lng` または `metadata_json` から再帰的に探索できるようにします。

### 2. プレミアム地理空間描画 (`render.ts` & `style.css`)
*   **曲線アーク (Great Circle Sim)**: `L.polyline` と二次ベジェ曲線アルゴリズムを使用し、ノード間の接続を滑らかな曲線で描画します。
*   **粒子アニメーション**: `requestAnimationFrame` を使用し、影響の「伝播速度」を波及強度（Intensity）に同期させた光の粒子をアーク上に走らせます。
*   **Market Pulse ラベル**: ガラスモーフィズム（`backdrop-filter`）を採用したフローティングラベルを実装し、予測変動率（+3.2%等）をリアルタイムに表示します。

### 3. ティア別表示ロジック (Ghost Nodes)
*   **CSS定義**: `.ghost-node` クラスに `grayscale(100%)` と `blur(2px)` を適用し、情報の「未取得状態」を視覚的に表現します。
*   **イベントバインド**: `is_locked` フラグを持つノードをクリックした際、アップセル用モーダルをトリガーするか、Subscription 画面へ誘導します。

### 4. マルチホップ対応
*   データ構造が「A → B → C」のような連鎖をサポートしている場合、再帰的に描画ループを回し、ノード間の依存関係を網の目のように視覚化します。

---

## Verification Plan

### Manual Verification (Browser)
1.  **ティア別挙動の確認**: 開発コンソールで `localStorage.getItem('user_tier')` を切り替えながら、ノードが「Ghost」になるか「フルカラー」になるかを確認。
2.  **アニメーションの滑らかさ**: アーク上の粒子が途切れず、一定のFPSを維持して流れているか確認。
3.  **座標フォールバック**: 座標がメタデータ内にしかないテストデータを用意し、正しくプロットされるか確認。
