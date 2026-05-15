# Official Data Sources

This document lists the primary official data sources used by the OSINT Analytics platform, categorized by their role in Pro (Quantitative) and Expert (Qualitative) analysis layers.

---

## 1. BEA (Bureau of Economic Analysis)

**Role:**
- GDP (Gross Domestic Product)
- NIPA (National Income and Product Accounts)
- GDP by Industry (Value Added, Gross Output)
- Input-Output Accounts (Inter-industry linkages)
- Regional Economic Accounts
- International Transactions (ITA)

**Pro Usage:**
- Quantitative analysis of macro demand, sectoral growth trends, regional economic shifts, and inter-industry ripples.

**Expert Usage:**
- Providing the foundational structural data for LLM interpretation of how specific alerts/news impact industry clusters, geographic regions, or aggregate demand.

**Official URL:**
- https://www.bea.gov/

---

## 2. Census Economic Census API

**Role:**
- Number of Establishments
- Sales, Value of Shipments, or Revenue
- Annual Payroll
- Number of Employees
- Industrial and Geographic Structural Data

**Pro Usage:**
- Quantifying industry/regional scale, assessing structural vulnerability, and tracking corporate activity density.

**Expert Usage:**
- LLM inference on how localized disasters, regulatory changes, or regional news events translate into broader economic impacts based on establishment density and payroll scale.

**Official URL:**
- https://www.census.gov/programs-surveys/economic-census/data/api.html

---

## 3. BLS PPI (Bureau of Labor Statistics - Producer Price Index)

**Role:**
- Producer Price Index (PPI)
- Price Pressure tracking
- Cost changes for Raw Materials, Intermediate Goods, and Final Demand

**Pro Usage:**
- Identifying sector-specific cost pressures, assessing pricing power, and quantifying margin compression risks.

**Expert Usage:**
- Correlating news events (e.g., supply chain strikes, resource shortages) with specific price pressure points to interpret future inflationary paths via LLM.

**Official URL:**
- https://www.bls.gov/ppi/databases/

---

## 4. Census International Trade API

**Role:**
- Exports and Imports (Value and Quantity)
- Trade by Country
- Trade by Commodity (HS Codes)
- Trade Dependency metrics

**Pro Usage:**
- Quantifying exposure to tariffs, export controls, supply chain bottlenecks, and foreign demand shifts.

**Expert Usage:**
- LLM reasoning on the second-order effects of geopolitical shifts, sanctions, or trade policy changes on specific corporate entities or industrial sectors.

**Official URL:**
- https://www.census.gov/foreign-trade/api_tool.html

---

## 5. FRED (Federal Reserve Economic Data)

**Role:**
- Interest Rates (Fed Funds, Treasury Yields)
- Commodity Prices (Crude Oil, Metals)
- Foreign Exchange (FX) Rates
- Credit Spreads and Financial Conditions
- Proxy for specific BLS/PPI series

**Pro Usage:**
- Quantifying financial shocks, energy cost impacts, credit environment shifts, and currency-related exposure.

**Expert Usage:**
- Analyzing the impact of Fed announcements, oil market news, or credit defaults on the broader investment landscape using LLM.

**Specific Series Candidates:**
- [PCUAINFOAINFO](https://fred.stlouisfed.org/series/PCUAINFOAINFO) (Producer Price Index by Industry: Information)

**Official URL:**
- https://fred.stlouisfed.org/
