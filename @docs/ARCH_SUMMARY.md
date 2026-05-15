# VELTRIXIA LABS / OSINT_analytics 引き継ぎサマリー

## 0. プロジェクト概要

現在開発しているのは、RSS/ニュースソースを起点に、各分野のシグナルを抽出し、構造データ・市場データ・地理情報・タイムライン・エクスポージャー分析を組み合わせて表示する **Intelligence Platform**。

プロダクト名/UI上のブランドは現在：

```text
VELTRIXIA LABS
```

主なUI構成：

```text
Free:
- Alert Stream
- Context Briefs
- Global Map

Pro:
- Pro Insights
  - Latest Structural Briefs
  - Pro Structural Brief 詳細

Subscription:
- Free
- Founding Pro
- Founding Expert
- Enterprise
```

当初は `Reports` や `Structural Briefs` が別ナビゲーションとして存在していたが、設計方針として **Pro Structural Brief は Pro Insights 内に統合**した。  
`Reports` はPro/Expert向けに将来的に生成する予定だったため、現行のナビからは削除してよい方針。

---

# 1. 料金設計

最終的に採用予定の価格設計は以下。

```text
Free: $0

Founding Pro:
$39/month
First 1,000 members only
Standard price: $79/month

Founding Expert:
$149/month
First 100 members only
Standard price: $299/month

Enterprise:
Contact us
```

方針：

```text
- Proは最初の1,000人限定で $39/month
- Expertは最初の100人限定で $149/month
- Standard priceを明示して「今入る理由」を作る
- Founding価格は locked while subscribed か first 12 months のどちらか検討中
```

個人的な推奨は：

```text
Founding Pro: $39/month locked while subscribed
Founding Expert: $149/month locked while subscribed
```

ただし、収益性を重視するなら：

```text
Founding Pro:
$39/month for first 12 months
then $59/month loyalty renewal
Standard Pro: $79/month

Founding Expert:
$149/month for first 12 months
then $249/month loyalty renewal
Standard Expert: $299/month
```

---

# 2. Subscription Plans UI

## 実装済み/方針

Subscription Plans 画面には以下のカードを表示：

```text
- Free Access
- Founding Pro
- Founding Expert
- Enterprise
```

画面上部に現在のSubscription Statusがあり、下に料金カードが並ぶ。

## 問題と修正

当初、料金カードが2列固定で、横幅があるのに空白が多かった。

原因は `web_dashboard/src/style.css` の `.plans-grid` が以下のように2列固定だったこと。

```css
.plans-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 2rem;
  margin: 1rem auto;
  max-width: 1100px;
}
```

修正方針：

```css
.plans-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(260px, 1fr));
  gap: 1.5rem;
  margin: 1rem auto;
  width: 100%;
  max-width: 1500px;
  align-items: stretch;
}
```

media query：

```css
@media (max-width: 1400px) {
  .plans-grid {
    grid-template-columns: repeat(2, minmax(280px, 1fr));
    max-width: 900px;
  }
}

@media (max-width: 768px) {
  .plans-grid {
    grid-template-columns: 1fr;
    max-width: 460px;
  }
}
```

`.plan-card--active` の拡大がレイアウト崩れの原因になり得るため、以下に修正：

```css
.plan-card--active {
  outline: 2px solid var(--plan-color);
  outline-offset: -2px;
  box-shadow: 0 0 20px color-mix(in srgb, var(--plan-color) 25%, transparent);
  transform: none;
}
```

Subscription Status も圧縮推奨：

```css
.sub-status-card {
  background: linear-gradient(135deg, var(--bg-secondary), color-mix(in srgb, var(--bg-secondary) 85%, var(--accent)));
  padding: 1.25rem 1.5rem;
  border-radius: 16px;
  border: 1px solid var(--border-active);
  box-shadow: var(--shadow-premium);
}
```

```css
.subscription-tab {
  display: flex;
  flex-direction: column;
  gap: 1.75rem;
  padding-bottom: 4rem;
}
```

---

# 3. ナビゲーション構成

## 現在の望ましい構成

Freeユーザー向け：

```text
- Alert Stream
- Context Briefs
- Global Map
```

Proユーザー向け：

```text
- Pro Insights
```

Subscription：

```text
- Subscription Plans
```

現在、`Reports` は不要。  
`Structural Briefs` も単独ナビでは不要。Pro Insights内の Latest Structural Briefs として表示する。

Expertは将来機能として、必要ならロックまたはComing Soon。

---

# 4. ローカル開発用Proアクセス

ローカル未ログイン状態では `/api/auth/me` が401になり、Free表示になっていた。  
Pro UI確認ができないため、ローカル開発限定のDev Overrideを実装した。

## 追加した環境変数

`.env` に追加：

```env
LOCAL_DEV_TIER=pro
VITE_DEV_TIER=pro
```

## Backend

`api/gating.py` に `LOCAL_DEV_TIER` を参照するロジックを追加。  
ただし、本番誤作動を避けるためローカル条件や `PRO_AUTOMATION_DRY_RUN=true` と組み合わせる安全装置を入れた。

## Frontend

`web_dashboard/src/main.ts` の未認証フォールバックで、`VITE_DEV_TIER=pro` かつ localhost/127.0.0.1 の場合は dev override user にする。

重要：

```text
user.id = 'dev-override'
tier = 'pro'
```

これにより左下表示：

```text
PRO ACCESS
Local Dev Override
```

になる。

## Vite設定

`web_dashboard/vite.config.ts` にルート `.env` を読めるよう `envDir: '../'` を追加した。

---

# 5. Pro Insights Hub UI

## 現状

Pro Insights Hub には上部に以下のカードがあった：

```text
Active Domains: 6
Automation State: DRY-RUN (STANDBY)
Domain Coverage: Energy / AI-Semi / Global Market / Supply Chain / Crypto / Defense
```

## ユーザー向け観点での判断

`Automation State: DRY-RUN (STANDBY)` は開発者向けで、顧客に見せるべきではない。  
「サービスが停止中・未完成」に見える可能性がある。

## 推奨修正

Pro Insights 上部は以下にする：

```text
Pro Insights Hub
Professional-grade structural intelligence across markets, geopolitics, supply chains, and technology.

Coverage Domains:
6 monitored domains

Analysis Layers:
Signals / Macro Data / Market Confirmation / Exposure Mapping

Monitored Domains:
Energy / AI-Semi / Global Market / Supply Chain / Crypto / Defense
```

削るもの：

```text
Automation State
DRY-RUN
STANDBY
```

対象ファイル：

```text
web_dashboard/src/modules/render/insights.ts
web_dashboard/src/style.css
```

---

# 6. 上部の最新情報バー / Pulse Bar

## 問題

`Alert Stream` では上部に最新情報バーが表示されるのは良い。  
しかし `Context Briefs` や `Pro Insights` にも表示されて邪魔だった。

原因は、`web_dashboard/src/main.ts` の共通レイアウト内に `#pulse-bar` があり、Alert Streamで描画された内容が他タブに残っていたため。

該当構造：

```ts
<div class="main-feed" id="alerts-container">
  <div id="pulse-bar" class="pulse-bar"></div>
  <div id="alerts-list"></div>
</div>
```

## 修正方針

`handleTabSwitch` の中で `tab === 'feed'` のときだけ表示、それ以外は非表示かつクリア。

追加例：

```ts
const pulseBarEl = document.querySelector<HTMLElement>('#pulse-bar');
if (pulseBarEl) {
    if (tab === 'feed') {
        pulseBarEl.style.display = 'block';
    } else {
        pulseBarEl.style.display = 'none';
        pulseBarEl.innerHTML = '';
    }
}
```

`renderIntelligenceFeed` で `renderLiveFeed` 前に：

```ts
if (data.alerts) {
    pulseBar.style.display = 'block';
    renderAlerts(data.alerts, alertsContainer, user!.tier);
    renderLiveFeed(data.alerts, pulseBar);
}
```

期待結果：

```text
Alert Stream: 表示
Context Briefs: 非表示
Pro Insights: 非表示
Global Map: 非表示
Subscription Plans: 非表示
```

---

# 7. Pro Structural Brief 自動生成パイプライン

## 実装済みPhase

Pro Structural Brief は以下のパイプラインで構成されている。

```text
AlertLog
→ Trigger Policy
→ Pro Structural Context
→ Pro Report Generator
→ Report DB保存
→ API
→ Pro Insights UI
```

主要ファイル：

```text
jobs/pro_brief_trigger_policy.py
analysis/pro_structural_context.py
reports/pro_structural_report_builder.py
jobs/pro_report_generator.py
jobs/pro_automation_manager.py
jobs/main_scheduler.py
api/routes/pro_reports.py
web_dashboard/src/modules/render/pro_reports.ts
```

## Trigger Policy

`jobs/pro_brief_trigger_policy.py`

実装内容：

```text
- severity: critical / elevated / high
- fidelity_score
- supporting_events_count / source_count
- structural_data_available
- market_data_available
- duplicate structural brief check
- domain-specific relaxed gate
```

Global Marketには緩和ゲートを追加済み：

```text
topic == global_market_intelligence
fidelity_score >= 0.6
evidence_count >= 4 or related_news_count >= 4
intelligence_score >= 0.3
structural_data_available == True
market_data_available == True
duplicate_structural_brief == False
```

Supply Chainなどには緩和ゲートは適用しない方針。

---

# 8. Pro Automation Manager

`jobs/pro_automation_manager.py`

実装済み：

```text
- run_once(dry_run=True)
- daily cap
- domain cap
- error handling
- enabled domains filter
- dry-run diagnostics
```

環境変数：

```env
ENABLE_PRO_AUTOMATION=true
PRO_AUTOMATION_DRY_RUN=true
PRO_AUTOMATION_INTERVAL_HOURS=6
PRO_AUTOMATION_LIMIT=5
PRO_AUTOMATION_ENABLED_DOMAINS=energy_resource_risk,ai_semiconductor_intelligence,global_market_intelligence,supply_chain_intelligence,crypto_geopolitics,defense_technology
```

現在は dry-run のまま。  
**まだ `PRO_AUTOMATION_DRY_RUN=false` にしていない。**

変更禁止として扱っていたもの：

```text
- Scheduler実生成ON
- Trigger Policy
- Automation caps
- PRO_AUTOMATION_DRY_RUN=false
```

---

# 9. Scheduler

`jobs/main_scheduler.py`

実装済み：

```text
- Pro automation hook
- safe_run concurrency guard
- interval env support
- scheduler heartbeat
```

過去にSchedulerが止まっていたことがあり、`scheduler_heartbeat` が更新されていなかった。  
そのため `scratch/check_scheduler_health.py` を作成した。

Scheduler起動コマンド：

```powershell
.venv\Scripts\python.exe jobs/main_scheduler.py
```

または uvicorn：

```powershell
.venv\Scripts\python.exe -m uvicorn api.main:app --host 127.0.0.1 --port 8000 --reload
```

---

# 10. RSS / Ingestion Pipeline

一度RSSインジェクションが停止していた。

原因：

```text
Schedulerプロセスが停止していた
scheduler_heartbeat が 2026-04-24 07:52 以降更新されていなかった
```

手動復旧スクリプトを作成：

```text
scratch/check_ingestion_status.py
scratch/check_system_metrics.py
scratch/run_ingestion_manual.py
scratch/run_pipeline_manual.py
```

手動復旧後：

```text
RawItem / Item / AlertLog が復旧
```

---

# 11. Pro Structural Brief 対象ドメイン

全6ドメインを調整済み。

```text
energy_resource_risk
ai_semiconductor_intelligence
global_market_intelligence
supply_chain_intelligence
crypto_geopolitics
defense_technology
```

各ドメインについて以下を `analysis/pro_domain_config.py` に定義・強化した。

```text
signal_classification_template
relevance_map
market_group_map
market_group_interpretation
watch_conditions
exposure_matrix_details
transmission_channels
watch_indicators
industry_keywords
```

---

# 12. ドメイン別品質状態

## Energy & Resource Risk

基準ドメイン。最も調整済み。

良い点：

```text
- Executive Summaryが自然
- Key Findingsあり
- Geo Context: South Korea / Iran / Gulf of Oman
- Timelineが時系列
- Market Confirmationがグループ別
  - Energy Producers
  - Oil Price Proxy
  - Transport Sensitivity
  - Petro FX
- Divergence Checkが自然
- Escalation / De-escalation Watchが実用的
- Exposure Matrixが具体的
```

Energyは基準版として扱う。

---

## Global Market Intelligence

UIは良いが、内容面で一度チューニング必要と判断。

問題：

```text
- Alert title と Timeline trigger がズレていた
- Geographic ContextにVenezuelaが混入
- Timelineが1件だけで弱い
- Quantitative Contextのタイトルが長い
- Structural Risk LOWの説明が不足
```

推奨修正：

```text
- Alert / Timeline / Geo Context のテーマ整合性を改善
- primary triggerは alert.title / target_label との類似度が高い related_news を優先
- related_newsはtitle overlapで低関連を除外/下位化
- Timeline 1件の場合は “Primary trigger only; corroborating timeline evidence is limited.” を表示
- Quantitative Contextは display_name / series_id / relevance の3段表示
- Market group labelsを整理
  - Risk Assets
  - Rates / Duration
  - Safe Haven / Real Assets
  - Inflation / Commodities
  - USD / FX Liquidity
```

その後、新規レポートでかなり改善済みのスクショが出ていた。

---

## AI / Semiconductor

確認観点：

```text
- SMH / SOXX / QQQ が AI/Semi demand / risk appetite として自然か
- USDTWD / USDKRW が supply chain / regional FX stress として自然か
- 金利やドルが単純にポジティブ扱いになっていないか
```

テスト生成済み report_id：

```text
21fd1452-9df3-49da-a3ff-b0f8498aee09
```

---

## Supply Chain

調整済み：

```text
- IYT / XLI / XLB / CARZ
- WPU101
- Industrial production
- Strategic minerals trade
```

Market group確認観点：

```text
- logistics
- industrial base
- materials
- automotive / transport
```

テスト生成済み report_id：

```text
ca60c75e-6294-4ed0-bdb9-4872ddfc0c90
```

---

## Crypto Geopolitics

調整済み：

```text
- BTC / ETH
- QQQ
- SPY
- TLT
- M2SL
- DTWEXBGS
- DGS10
```

確認観点：

```text
- BTC/ETHをrisk appetite / liquidity proxyとして扱う
- M2 / USD / TLTとの関係を断定しすぎない
- regulatory/geopolitical contextが弱くなりすぎない
```

テスト生成済み report_id：

```text
73335fd7-75c3-4a34-a00e-22c195a3ace8
```

---

## Defense Technology

調整済み：

```text
- ITA / XAR / PPA / XLI
- FDEFX
- aerospace PPI
- defense spending
- aerospace trade
```

方針：

```text
軍事的断定ではなく、
調達・産業基盤・供給制約・予算サイクルとして表現
```

テスト生成済み report_id：

```text
6c4e836c-6d92-4486-8b62-34cd72e5ed2d
```

---

# 13. Pro Structural Brief UI / structured_payload化

## 旧状態

以前は `content_markdown` をそのまま表示するだけで、長文Markdown中心だった。

## 新状態

Reportに `structured_payload` を追加し、Frontendで構造化UIを表示する方式に移行。

## DB Migration

`Report` モデルに追加：

```python
structured_payload = Column(JSONB, nullable=True)
```

Migrationファイル：

```text
1667481b0033_add_structured_payload_to_reports.py
```

SQLite/PostgreSQL両対応のため、Migrationでは以下のように調整：

```python
sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql')
```

実行済み：

```powershell
.venv\Scripts\python.exe -m alembic upgrade head
```

---

# 14. Payload Builder

`reports/pro_structural_report_builder.py`

実装した主な関数：

```text
build_pro_structural_report_payload(context)
```

Payloadに含める内容：

```text
domain
signal
executive_summary
key_findings
signal_classification
geographic_context
event_timeline
transmission_flow
structural_context
market_confirmation
divergence_check
contradictory_signals
watch_conditions
watch_indicators
balanced_interpretations
exposure_matrix
coverage_matrix
data_notes
```

`jobs/pro_report_generator.py` で、Report保存時に：

```python
content_markdown = ...
structured_payload = build_pro_structural_report_payload(context)
```

を保存。

API詳細レスポンス `GET /api/pro/reports/{id}` で `structured_payload` を返すよう変更済み。  
一覧APIには含めない方針。

---

# 15. Pro Structural Brief Frontend

`web_dashboard/src/modules/render/pro_reports.ts`

実装方針：

```ts
if (report.structured_payload && Object.keys(report.structured_payload).length > 0) {
    renderStructuredProBrief(...)
} else {
    simpleMarkdown(report.content_markdown)
}
```

これにより既存レポートはMarkdown fallback、新規レポートはIntelligence UI。

UI構成：

```text
- Header / Hero
- Status cards
  - Structural Risk
  - Market Status
  - Data Coverage
  - Data Lag
- Executive Summary
- Signal Classification
- Geographic Context
- Event Timeline
- Structural Impact & Transmission
- Quantitative Context
- Market Confirmation
- Divergence Check
- Contradictory / Unresolved Signals
- Escalation / De-escalation Watch
- Watch Indicators
- Balanced Assessment
- Exposure Matrix
- Source Coverage Matrix
- Data Notes & Coverage Limitations
- Footer: NOT INVESTMENT ADVICE
```

CSSは `web_dashboard/src/style.css` に `.intel-*` 系を追加。

---

# 16. Intelligence Report UI の品質改善

段階的に改善した内容：

```text
- Executive Summaryが空にならないよう修正
- Key Findingsを追加
- Market group status のラベルを拡張
- risk_on / flight_to_safety / inflationary / usd_strength / usd_weakness / resilient などもKey Findings対象にした
- Event Timelineを時系列に修正
- Timeline roleに MARKET_REACTION を追加
- Quantitative Contextを意味ベースタイトルに変更
- Market Confirmation groupにsubtext/interpretationを追加
- Divergence Checkの矛盾文言を修正
- Contradictory / Unresolved Signalsを追加
- Data Notesを折りたたみに変更
- Footerを CONFIDENTIAL ANALYSIS から NOT INVESTMENT ADVICE に変更
```

注意：

```text
金融・市場データを扱うため、NOT INVESTMENT ADVICE は維持すること。
```

---

# 17. Global Map / Location

`db/models.py` には `AlertLog` や `Report` に以下がある。

```text
location_lat
location_lng
```

`processor/location_resolver.py` に地理抽出処理がある。  
Leafletは `web_dashboard/src/modules/render/map.ts` で使用済み。

Pro Brief詳細画面でMini Mapを出す構想があり、`structured_payload.signal.location_lat/lng` が存在する場合のみ表示する方針。  
ただし、現状多くのレポートでは座標がなく、`Geo Confidence: Inferred` と地域チップ表示が中心。

---

# 18. 生成済みテストレポート

全ドメインのテスト生成で確認済み。

```text
Global Market Intelligence:
52cead14-24bb-4ce5-9527-edd14eec95ba

AI & Semiconductor Intelligence:
21fd1452-9df3-49da-a3ff-b0f8498aee09

Supply Chain Intelligence:
ca60c75e-6294-4ed0-bdb9-4872ddfc0c90

Crypto Geopolitics:
73335fd7-75c3-4a34-a00e-22c195a3ace8

Defense Technology:
6c4e836c-6d92-4486-8b62-34cd72e5ed2d
```

Energyは既存スクショで基準確認済み。

検証サマリー：

```text
scratch/pro_structured_domain_validation_summary.md
```

---

# 19. 重要なScratchファイル

作成済み/使用済み：

```text
scratch/test_pro_report_generator.py
scratch/test_pro_brief_trigger_policy.py
scratch/test_pro_automation_manager.py
scratch/test_pro_scheduler_hook.py
scratch/list_top_alerts.py
scratch/check_pro_automation_dry_run_status.py
scratch/check_ingestion_status.py
scratch/check_scheduler_health.py
scratch/run_ingestion_manual.py
scratch/run_pipeline_manual.py
scratch/run_pro_real_test.py
scratch/run_pro_cycle_test.py
scratch/run_pro_domain_tuning.py
scratch/test_gen_all_domains.py
scratch/pro_structured_domain_validation_summary.md
scratch/pro_ui_manual_review_index.md
```

Markdown出力例：

```text
scratch/pro_real_generation_energy_test.md
scratch/pro_real_generation_global_market_test_refined.md
scratch/pro_manual_supply_chain_report_refined.md
scratch/pro_manual_crypto_report_refined.md
scratch/pro_manual_defense_report_refined.md
scratch/pro_structured_global_market_intelligence_test.md
scratch/pro_structured_ai_semiconductor_intelligence_test.md
scratch/pro_structured_supply_chain_intelligence_test.md
scratch/pro_structured_crypto_geopolitics_test.md
scratch/pro_structured_defense_technology_test.md
```

---

# 20. ビルド・起動コマンド

Frontend build：

```powershell
npm.cmd run build
```

Backend import check：

```powershell
.venv\Scripts\python.exe -c "from api.main import app; print('API OK')"
```

API server：

```powershell
.venv\Scripts\python.exe -m uvicorn api.main:app --host 127.0.0.1 --port 8000 --reload
```

Scheduler：

```powershell
.venv\Scripts\python.exe jobs/main_scheduler.py
```

Dashboard URL：

```text
http://127.0.0.1:8000/app.html
```

Pro Insights：

```text
http://127.0.0.1:8000/app.html#pro-insights
```

---

# 21. API / Router修正

過去に Pro Reports API が `/api/api/pro/reports` になっていた問題があった。  
`api/routes/pro_reports.py` の router prefix を修正。

修正後の想定：

```text
/api/pro/reports
/api/pro/reports/{report_id}
```

---

# 22. 重要な注意点

## まだ実生成ONにしていない

```env
PRO_AUTOMATION_DRY_RUN=true
```

これはまだ維持。

本番自動生成をONにするには：

```env
PRO_AUTOMATION_DRY_RUN=false
```

だが、まだ最終UI/品質確認が終わるまでは変更しない。

## Trigger Policyは安定済み

安易に緩めない。  
Global Market relaxed gateのみ特例あり。

## LLM / Expert / Forecastはまだ使わない

現状Pro Structural Briefは静的ルール・構造データ・市場データベースで生成。  
Expert/Forecast機能は将来。

## 既存レポートpayloadを直接手動編集しない

新しいロジック確認は、新規手動生成で行う。

---

# 23. 次にやるべきこと

## 直近タスク1: Pro Insights Hub上部の整理

`Automation State: DRY-RUN (STANDBY)` をユーザーUIから消す。  
代わりに：

```text
Coverage Domains
Analysis Layers
Monitored Domains
```

を表示。

対象：

```text
web_dashboard/src/modules/render/insights.ts
web_dashboard/src/style.css
```

## 直近タスク2: Global Market の最終確認

Global Marketはかなり改善したが、他ドメインより抽象的なので要確認。

特に：

```text
- Alert title / Timeline / Geo Contextの整合性
- Market group status
- Structural Risk LOWの説明
- News EvidenceがMEDIUMなのにTimelineが少なすぎないか
```

## 直近タスク3: AI/Semi, Supply Chain, Crypto, Defense のUI手動確認

EnergyとGlobal Marketを基準に、各ドメイン1件ずつ確認。

確認観点：

```text
- Executive Summary
- Key Findings
- Signal Classification
- Geographic Context
- Event Timeline
- Quantitative Context
- Market Confirmation
- Divergence Check
- Contradictory Signals
- Escalation Watch
- Exposure Matrix
- Coverage Matrix
- Data Notes
- Footer
```

## 直近タスク4: Subscription Plans の最終調整

カード横並びは修正済み。  
次は以下を確認：

```text
- 4列表示
- 2列/1列レスポンシブ
- Founding Pro/Expertの強調が過剰でないか
- 現在プラン表示が自然か
- CTA文言
```

---

# 24. 他AIへの重要な開発方針

このプロジェクトでは、ユーザーは **AIの使用量を抑えるため、ブラウザUI確認は自分で行う**方針。  
そのため、今後の指示では：

```text
- Browser Subagentは使わない
- UI確認はユーザーが行う
- こちらはコード変更・build確認・確認ポイント提示まで
```

を前提にすること。

また、Antigravityへの指示は、抽象的にしすぎると処理がループすることがあった。  
今後は、修正対象ファイル・対象クラス・置換前/置換後をできるだけ明示する。

良い指示形式：

```text
対象ファイル:
web_dashboard/src/style.css

このセレクタを探す:
.plans-grid

既存定義を丸ごと以下に置き換える:
...
```

避けるべき指示：

```text
UIをいい感じに高級感あるようにして
```

---

# 25. 最後の状態

このチャット終了時点の大まかな状態：

```text
- Pro Structural Brief生成パイプライン完成
- structured_payload DB保存対応済み
- Intelligence Report UI対応済み
- 全6ドメイン config調整済み
- 全6ドメイン dry-run対象
- 自動生成はまだ dry-run
- Pro Insights内にStructural Briefを統合済み
- FreeナビはAlert / Context / Map中心
- Subscription価格設計決定
- Subscription Plans UIは横並び修正中/修正済み
- Pulse barはAlert Streamのみ表示に修正済み
- 次はPro Insights Hub上部の顧客向け整理
```

---

# 26. 最重要ファイル一覧

```text
Backend:
db/models.py
api/gating.py
api/main.py
api/routes/pro_reports.py
jobs/main_scheduler.py
jobs/pro_automation_manager.py
jobs/pro_brief_trigger_policy.py
jobs/pro_report_generator.py
analysis/pro_structural_context.py
analysis/pro_domain_config.py
reports/pro_structural_report_builder.py

Frontend:
web_dashboard/src/main.ts
web_dashboard/src/modules/render/nav.ts
web_dashboard/src/modules/render/insights.ts
web_dashboard/src/modules/render/pro_reports.ts
web_dashboard/src/modules/render/utils.ts
web_dashboard/src/modules/render/map.ts
web_dashboard/src/style.css
web_dashboard/vite.config.ts

Diagnostics / scratch:
scratch/check_pro_automation_dry_run_status.py
scratch/test_gen_all_domains.py
scratch/pro_structured_domain_validation_summary.md
scratch/pro_ui_manual_review_index.md
scratch/check_scheduler_health.py
scratch/check_ingestion_status.py
```

