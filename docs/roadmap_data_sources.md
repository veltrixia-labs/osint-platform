# Data Sources Roadmap

This roadmap tracks the integration status of official economic and market data sources into the OSINT Analytics platform.

---

## 1. Status Overview

### ✅ Completed
- **BEA GDP by Industry:** Automated fetching, normalization, and DB storage (2018–2024).
- **BEA NIPA (Macro):** Key tables (T10101, T10105, T20305) integrated (2018–2024).
- **BLS PPI:** Core series (Final Demand, Goods, Services, Energy, etc.) integrated (2018–2024).
- **Pro Baseline Analysis:** Integrated BEA x BLS growth vs. price pressure analysis.
- **Pro Report Generation:** Initial JSON builder for consolidated quantitative snapshots.

### ⏳ Pending (Unimplemented)
- **FRED Integration:** Connection to St. Louis Fed API for interest rates, commodities, and FX.
- **Census Economic Census:** Integration for business establishment and regional payroll data.
- **Census International Trade:** Integration for HS commodity-level export/import data.
- **BEA Expansion:** Input-Output tables, Regional accounts, and International Trade in Services (ITA).

---

## 2. Implementation Roadmap

### Phase A: Core Pro Expansion
1. **FRED API Connection:** Establish client and fetch PCUAINFOAINFO (Information Industry PPI proxy).
2. **Census Economic Census Investigation:** Research API endpoints for establishment density.
3. **Census International Trade API Investigation:** Research commodity/country trade mapping.

### Phase B: Alert-Driven Pro Reports
4. **Alert-to-Data Mapping:** Logic to link News keywords to specific NIPA/PPI/Trade categories.
5. **Dynamic Pro Report Generator:** Generate snapshots tailored to a specific incoming alert.

### Phase C: Expert Intelligence Pipeline
6. **Expert LLM Schema:** Define the JSON input format for the Expert LLM (combining Pro data + News).
7. **Expert Analysis Engine:** Implementation of LLM prompts for strategic ripple analysis.

---

## 3. Recommended Implementation Order

1. **Fix Pro / Expert Specifications** (Completed)
2. **Establish `official_data_sources.md`** (Completed)
3. **FRED API Connectivity Check**
4. **Census Economic Census API Discovery**
5. **Census International Trade API Discovery**
6. **Alert-driven Pro Mapping Logic**
7. **Alert-driven Pro Report Automation**
8. **Expert LLM Input Schema Finalization**
9. **Expert LLM Strategic Analysis Implementation**
