# Domain Validation Summary

## Global Market Intelligence
- **Report ID:** 52cead14-24bb-4ce5-9527-edd14eec95ba
- **Structured Payload:** Present
- **Status:** PASS
- **Highlights:** `risk_on`, `inflationary`, `usd_weakness` mapped successfully. Macro observations enriched beautifully with display names like "Federal funds rate — overnight borrowing cost benchmark".
- **Refinements made:** Added new directional terms to `_build_executive_summary` logic to ensure domain-specific semantic labels are included in Key Findings.

## AI & Semiconductor Intelligence
- **Report ID:** 21fd1452-9df3-49da-a3ff-b0f8498aee09
- **Structured Payload:** Present
- **Status:** PASS
- **Highlights:** `Tech Beta` (QQQ) accurately captured as `risk_on`. The `Tech-Sensitive FX` explicitly ties USD strength to export revenue risk in the description, demonstrating domain-aware inference. 

## Supply Chain Intelligence
- **Report ID:** ca60c75e-6294-4ed0-bdb9-4872ddfc0c90
- **Structured Payload:** Present
- **Status:** PASS
- **Highlights:** Correctly captured `resilient` states for Industrial Production (XLI) and Transport & Logistics (IYT) while input materials were `easing`. The nuanced divergence interpretation ("situation is evolving; directional clarity has not yet emerged") fits perfectly.

## Crypto Geopolitics
- **Report ID:** 73335fd7-75c3-4a34-a00e-22c195a3ace8
- **Structured Payload:** Present
- **Status:** PASS
- **Highlights:** `Digital Assets` confirming, `Correlated Risk Assets` risk_on. M2SL and DTWEXBGS descriptions explicitly reference macro liquidity drivers for digital assets. No deterministic LLM statements were generated.

## Defense Technology
- **Report ID:** 6c4e836c-6d92-4486-8b62-34cd72e5ed2d
- **Structured Payload:** Present
- **Status:** PASS
- **Highlights:** `Defense Equities` (ITA/XAR/PPA) showed `easing`, whilst the `Industrial Base` (XLI) showed `confirming`. This contrast was mechanically captured, leading to a valid divergence flag: "Market prices are moving but structural data shows limited disruption".

## System Checks
- **Market Group Interpretation:** Verified across all 5 domains. `SPY/QQQ` reliably map to `risk_on/stress`. `ITA` maps to procurement outlook. `BTC/ETH` maps to core crypto risk appetite.
- **Data Coverage:** Successfully evaluated as moderate/strong without false "limited" claims.
- **Config Changes:** No config changes were necessary to `pro_domain_config.py` itself since the templates were already rich and well-structured. However, a crucial fix was applied to `_build_executive_summary` to recognize the new directional terms (`risk_on`, `flight_to_safety`, etc.) so they appear in Key Findings.
