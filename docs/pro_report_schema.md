# Pro Report JSON Schema

This document defines the standardized JSON structure for Pro-level quantitative reports.

---

## 1. Top-Level Structure

| Field | Type | Description |
|-------|------|-------------|
| `report_type` | `string` | Always `"pro"` for quantitative reports. |
| `version` | `string` | Schema version (e.g., `"0.1"`). |
| `as_of_year` | `integer` | Primary annual context. |
| `as_of_date` | `string` | Specific month/date context (YYYY-MM). |
| `sections` | `object` | Container for individual analysis snapshots. |
| `metadata` | `object` | Generation timestamps and audit trails. |

---

## 2. Section: `macro_snapshot`

| Field | Type | Description |
|-------|------|-------------|
| `gdp_current_dollars_t` | `float` | Nominal GDP in Trillions of USD. |
| `gdp_growth_rate_pct` | `float` | Real GDP growth rate (%). |
| `pce_current_dollars_t` | `float` | Personal Consumption Expenditures in Trillions. |
| `pce_gdp_ratio_pct` | `float` | PCE as a percentage of GDP. |

---

## 3. Section: `industry_snapshot`

An array of objects representing top sectors by GDP share.

| Field | Type | Description |
|-------|------|-------------|
| `industry_code` | `string` | BEA industry code (e.g., `"31G"`). |
| `industry_description` | `string` | Human-readable name. |
| `value_billions` | `float` | Gross output in Billions. |
| `share_pct` | `float` | Share of total private/aggregate GDP. |

---

## 4. Section: `price_pressure_summary`

High-level indicators from BLS PPI analysis.

| Field | Type | Description |
|-------|------|-------------|
| `high_risk_series` | `array` | Series showing significant margin or cost risk. |
| `easing_pressure_series` | `array` | Series showing deflationary or cooling trends. |
| `summary_metadata` | `object` | Counts of risks vs. total series analyzed. |

---

## 5. Signal Categories (`risk_signals`, `pricing_power_signals`, etc.)

Objects containing integrated BEA/BLS comparison results.

| Field | Type | Description |
|-------|------|-------------|
| `ppi_series_id` | `string` | BLS Series ID. |
| `ppi_label` | `string` | Descriptive label. |
| `ppi_yoy_pct` | `float` | Year-over-year PPI change. |
| `ppi_cumulative_pct` | `float` | Cumulative PPI change since baseline (2018). |
| `ppi_latest_value` | `float` | Most recent index value. |
| `ppi_latest_date` | `string` | Date of the latest value (YYYY-MM). |
| `bea_industry_code` | `string` | Mapped BEA industry code. |
| `bea_industry_growth_pct` | `float` | Mapped industry value-added growth rate. |
| `signal` | `string` | `margin_pressure_risk`, `growth_with_pricing_power`, etc. |
