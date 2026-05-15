# Pro vs. Expert Analysis Specifications

This document defines the architecture and functional boundaries between the Pro (Quantitative) and Expert (Qualitative) analysis layers of the OSINT Analytics platform.

---

## 1. Pro Analysis (Quantitative & Fact-Driven)

The Pro layer is triggered by incoming signals (Alerts/News) and serves as the data-gathering engine that grounds the analysis in hard statistics.

**Workflow:**
- **Entry Point:** Triggered by an RSS feed item, Alert, or News signal.
- **Data Discovery:** Identifies relevant statistical indicators, market data, industrial growth metrics, price pressures, and trade dependencies based on the signal's context.
- **Data Sources:** Utilizes official APIs (BEA, BLS, FRED, Census, International Trade) to fetch and normalize historical and recent observations.
- **Quantitative Output:** Generates snapshots showing:
    - Sectoral growth vs. price pressure.
    - Regional exposure to specific shocks.
    - Trade dependency on impacted countries/commodities.
    - Identification of potentially impacted corporate entities.

**Constraint:**
- **No Subjective Interpretation:** The Pro layer does NOT perform LLM-based forecasting, scenario generation, or qualitative reasoning. It only presents what the data says *currently* and *historically*.

---

## 2. Expert Analysis (Qualitative & LLM-Driven)

The Expert layer takes the quantitative foundation built by the Pro layer and adds a layer of intelligent interpretation.

**Workflow:**
- **Input:** Receives the Pro-generated quantitative results, the original Alert/News text, identified corporate stakeholders, and relevant industry/market indices.
- **LLM Interpretation:** Processes the combined context to:
    - Analyze ripple effects through supply chains.
    - Predict future trajectories and risk scenarios.
    - Evaluate specific impacts on individual corporate entities.
    - Synthesize a "Strategic Outlook" that translates numbers into actionable intelligence.

**Goal:**
- **Actionable Intelligence:** Providing a deep-dive analysis that answers "What does this actually mean for my portfolio/strategy?" by combining hard data with sophisticated reasoning.

---

## 3. Clear Boundary

| Feature | Pro Layer | Expert Layer |
|---------|-----------|--------------|
| **Core Method** | Statistical Queries / API Fetching | LLM Reasoning / Contextual Synthesis |
| **Output Type** | Data Tables, Indices, Growth Rates | Narrative Analysis, Risk Scenarios, Predictions |
| **Data Usage** | Fetching and Normalizing | Interpreting and Correlating |
| **Human Tone** | Objective, Analytical | Insightful, Strategic |
| **Primary Goal** | Grounding in Fact | Projecting the Future |
