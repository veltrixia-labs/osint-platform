# Implementation Plan: UX & Monetization Tiers (Phase 4.1)

本計画では、「第2次波及効果」の視覚化をプレミアム化し、商用化に向けたプラン別アクセス制限（ティア分け）を実装します。

## Proposed Changes

### 1. Visual: Premium Propagation Map (UX)
*   **Great Circle Arcs**: 直線ではなく、地球の曲率を考慮した流麗なアークを描画します。
*   **Glassmorphism Pulse**: ステークホルダー拠点に、半透明の「マーケット・パルス」オーバーレイを表示。`Impact Alpha` を一目で把握可能にします。
*   **Animation**: 影響の強さに応じてアークの光の速度を動的に変更。

### 2. Logic: Plan-based Content Gating (Monetization)
*   **Access Middleware**: ユーザーの `plan_level` (free/pro/expert) に基づき、APIレスポンスの `cascading_impacts` や `report_detail` をフィルタリングします。
*   **Ghost Nodes**: 未契約プランで見れるはずの波及先を「鍵付きアイコン」や「ぼかし」で表示し、アップセルを促します。

### 3. Intelligence: Tiered Report Generation
*   **Prompt Adjustment**: 
    - `Pro`: 第1次波及（直接的なサプライヤー等）までを詳細化。
    - `Expert`: 第3次以上の連鎖、および「自己学習エンジン」による重み付け根拠を含むフルレポート。

## Verification Plan

### Automated Tests
*   `test_api_gating.py`: Freeユーザーでアクセスした際、`cascading_impacts` が空または制限されていることを確認。
*   `test_report_tiering.py`: プロンプトにプラン属性が正しく渡されていることを確認。

### Manual Verification
*   ダッシュボードでプランを切り替え、マップ上のアークの表示範囲が変わることを目視確認。
