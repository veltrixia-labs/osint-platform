# Phase 4: Cascading Impact & Self-Learning Engine (Refined)

## 1. Goal Description
Evolve the OSINT platform into a "Second-Order Decision Engine" that predicts market and geopolitical shifts. This phase implements automated stakeholder discovery across 7 core domains and introduces a **Self-Learning Feedback Loop** that cross-references predictions with actual market data, isolated from macro-noise.

## 2. Strategic Refinements (Post-Gemini Scrutiny)

### [Architecture] JSON to RDB Migration
> [!IMPORTANT]
> To prevent data corruption during concurrent self-learning writes, we will migrate `corporate_graph.json` to the existing **SQLite** database.
- **`Stakeholder` Table**: Stores entity metadata (Ticker, Name, Domain).
- **`Dependency` Table**: Stores relational edges (`exposure_weight`, `beta_correlation`, `substitution_elasticity`).

### [Algorithm] Alpha-Beta Signal Separation
> [!TIP]
> To avoid "False Learning", the Feedback Loop will subtract the baseline market index (e.g., S&P 500 or Sector Index) from the entity's price movement to isolate the **Event Alpha** (True Impact).

### [Domain] Digital Infrastructure Expansion
- Added **Digital Infrastructure & Cybersecurity** (Cloud nodes, Subsea cables, Major IXPs) as a 7th cross-cutting domain to monitor systemic digital chokepoints.

## 3. Core Domains (7-Domain Portfolio)
- **AI & Semiconductors** (ASML, TSMC, BIS)
- **Global Market** (FED, SWIFT)
- **Energy & Resource** (OPEC+, CATL)
- **Supply Chain** (Maersk, Chokepoints)
- **Defense Tech** (Lockheed, Starlink)
- **Crypto & Geopolitics** (Binance, USDT)
- **Digital Infrastructure & Cyber** (AWS, Azure, Subsea Cables) -- *NEW*

## 4. Technical Implementation

### [Backend]
- **`processor/impact_discovery.py`**: LLM-driven extractor for 2nd-order entities.
- **`jobs/learning_loop.py`**: Cron-job to audit predictions.
    - Fetch Market Data (Base + Index).
    - Calculate `Delta = EventImpact - MarketBaseline`.
    - Update DB weights via Transactions.

### [Frontend]
- **Propagation Animations**: Animated arcs on the Global Map.
- **Market Overlays**: Sparkline charts for "Impact Alpha" intensity.

## 5. Verification Plan
- **Verification**: Execute a simulated "Azure Cloud Outage" and verify that the system correctly maps impacts on the "Digital Infrastructure" domain and downstream SaaS stakeholders.
- **Learning Audit**: Verify that SQLite weights are updated correctly after a simulated market event without file conflicts.
