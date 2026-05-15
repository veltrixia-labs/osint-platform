# BEA Dataset Expansion Plan for OSINT Analytics

This document outlines the plan for expanding the BEA data integration to support high-fidelity Pro and Expert tier analysis.

## Core Strategy

- **Pro Analysis**: Focuses on quantitative trends, growth rates, and structural shifts using macro and sectoral data (NIPA, GDPbyIndustry, InputOutput).
- **Expert Analysis**: Contextualizes these trends with external events (news, alerts) and uses LLMs to interpret the "why" and "what's next," leveraging more granular data (Regional, ITA, UnderlyingGDPbyIndustry).

---

## 1. BEA Dataset Metadata Summary

Based on API exploration, the following datasets are prioritized:

| Dataset Name | Description | Key Parameters | Priority |
|--------------|-------------|----------------|----------|
| **GDPbyIndustry** | Industry-level value added, gross output, and compensation. | `TableID`, `Frequency`, `Year`, `Industry` | **A (Implemented)** |
| **NIPA** | National Income and Product Accounts (Macro GDP, Consumption, Investment). | `TableName`/`TableID`, `Frequency`, `Year` | **A** |
| **InputOutput** | Relationships between industries (Supply Chain / Multipliers). | `TableID`, `Year` | **A** |
| **Regional** | State, County, and MSA level economic indicators. | `GeoFips`, `LineCode`, `TableName`, `Year` | **B** |
| **ITA** | International Transactions Accounts (Trade, Balance of Payments). | `Indicator`, `AreaOrCountry`, `Frequency`, `Year` | **B** |
| **UnderlyingGDPbyIndustry** | More granular industry breakdowns and supplementary metrics. | `TableID`, `Frequency`, `Year`, `Industry` | **B** |

---

## 2. Dataset Details & Utility

### Priority A: Macro & Structural Foundation

#### [NIPA] (National Income and Product Accounts)
- **Primary Metrics**: Real GDP, Personal Consumption Expenditures (PCE), Gross Private Domestic Investment, Exports/Imports, Government Spending.
- **Pro Utility**: Tracks macro demand drivers. Identify if growth is consumption-led vs. investment-led.
- **Expert Utility**: Match interest rate news (Fed) with fixed investment trends or inflation news with PCE data.
- **Next Step**: Define `bea_nipa` table. Key challenge: Mapping `TableName` (e.g., "T10101") to human-readable concepts.

#### [InputOutput] (Input-Output Data)
- **Primary Metrics**: Use Tables, Make Tables, Requirements Tables (Multipliers).
- **Pro Utility**: Identify which industries are critical suppliers to others. Model ripple effects of price changes (Cost-Push inflation).
- **Expert Utility**: Map geopolitical disruptions (e.g., Suez Canal) to specific downstream industries using IO coefficients.
- **Next Step**: Research Table IDs for "Requirements" (multipliers).

---

### Priority B: Granularity & External Exposure

#### [Regional] (Regional Data)
- **Primary Metrics**: State GDP, Personal Income by County, Employment by Region.
- **Pro Utility**: Heatmaps of economic activity. Identify regional growth outliers.
- **Expert Utility**: Match weather events or regional policy changes (e.g., California regulations) with localized economic impact.
- **Next Step**: Narrow down `GeoFips` (State level is highest priority).

#### [ITA] (International Transactions Accounts)
- **Primary Metrics**: Trade in Goods and Services, Primary/Secondary Income.
- **Pro Utility**: Foreign demand sensitivity. Trade balance trends.
- **Expert Utility**: Map tariff news, trade wars, or currency fluctuations to specific trade balance components.
- **Next Step**: Identify key `Indicator` codes (e.g., "GoodsExports").

#### [UnderlyingGDPbyIndustry]
- **Primary Metrics**: More detailed industry sub-segments.
- **Pro Utility**: Deeper dive into sectors identified in GDPbyIndustry.
- **Expert Utility**: Very specific industry news (e.g., specific manufacturing niche) matched with underlying data.

---

## 3. Implementation Roadmap

### Phase 1: NIPA Integration (Next)
1. **Model**: Create `BEANipa` model (Table: `bea_nipa`).
2. **Repository**: Implement upsert for NIPA.
3. **Query**: Functions for `get_gdp_components(year)`, `get_consumption_trend()`.
4. **Validation**: Compare with `GDPbyIndustry` total GDP.

### Phase 2: InputOutput Mapping
1. **Focus**: Identify the "Requirements" tables to calculate "Exposure Weights."
2. **Integration**: Link with `stakeholders` and `dependencies` tables to enhance AI impact discovery.

### Phase 3: Regional & International
1. **Regional**: Start with State-level GDP.
2. **International**: Start with top-level Trade balance.

---

## 4. Technical Considerations

- **Table Normalization**: Each dataset has unique columns (e.g., `GeoFips` in Regional, `Indicator` in ITA). We should keep tables independent rather than one giant "BEA" table.
- **Note Handling**: Continue the pipe-separated `note_text` pattern established in `GDPbyIndustry`.
- **Unit Management**: BEA units vary (Billions vs. Millions vs. Index). Store units explicitly in a metadata column.
