# Alert-Driven Pro Report Design

This document outlines the design for the next phase of the Pro analysis layer: generating quantitative reports dynamically in response to specific news alerts.

---

## 1. Concept

Current Pro reports are "periodic" snapshots (e.g., 2024 Year-End). An **Alert-Driven Pro Report** is a "contextual" snapshot triggered by an incoming intelligence signal (RSS, News, Alert).

**Example:**
- **Signal:** "Major port strike in Long Beach."
- **Response:** Generate a Pro report focusing on Transportation (48TW), Retail Inventory (44RT), and Trade Dependency from Asia.

---

## 2. Technical Workflow

1. **Signal Ingestion:** A new `AlertLog` entry is created (via Scout Job).
2. **Context Extraction:** NLP/Keyword mapping identifies the primary sector and region (e.g., "Transportation", "Logistics").
3. **Data Mapping:**
    - **BEA:** Fetch Value Added and Share for mapped sectors.
    - **BLS:** Fetch relevant PPI series (e.g., Trucking, Warehousing).
    - **Census:** Fetch International Trade data for the impacted ports/regions.
4. **Report Assembly:** Assemble a Pro report JSON focused on the *delta* and *exposure* related to the signal.

---

## 3. Key Mapping Logic

To enable automation, we will maintain a `keyword_to_data_map`:

| Keyword | BEA Sector | BLS PPI | Census Trade |
|---------|------------|---------|--------------|
| "Energy", "Oil" | 21, 22 | WPU057 | Oil Imports/Exports |
| "Semiconductor" | 334 | WPU117 | HS 8542 Trade |
| "Construction" | 23 | WPU081, WPU101 | Steel/Lumber Trade |
| "Retail", "Consumer"| 44RT | WPUFD4 | Consumer Goods Imports |

---

## 4. Integration with Expert Layer

The Alert-Driven Pro report serves as the **Evidence Bundle** for the Expert LLM. 

Instead of asking the LLM to "guess" the impact, we provide:
- "The impacted sector (334) accounts for X% of GDP and has seen Y% cost pressure recently."
- This allows the Expert LLM to provide a much higher fidelity risk assessment.
