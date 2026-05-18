"""
Pro Structural Brief Domain Configuration.

Centralized configuration for the 6 intelligence domains, mapping structural 
economic data sources to market confirmation instruments.
"""

from typing import Dict, Any, List, Optional

PRO_DOMAIN_CONFIG = {
    "energy_resource_risk": {
        "domain_id": "energy_resource_risk",
        "display_name": "Energy & Resource Risk",
        "primary_user_question": "How do structural energy shifts and resource scarcity impact supply chain stability and inflation?",
        "primary_asset_classes": ["energy equities", "commodities", "inflation-linked assets", "oil-sensitive FX"],
        "decision_relevant_questions": [
            "Is this signal more likely to affect supply expectations, price pressure, or policy enforcement?",
            "Which commodity-sensitive sectors are exposed?",
            "Does the signal reinforce or contradict current WTI / PPI energy trends?"
        ],
        "structural_data": {
            "fred_series": ["DCOILWTICO", "GASREGW"],
            "bls_series": ["WPU05", "WPU051"],
            "eia_series": ["WCESTUS1", "WPULEUS3", "WCRFPUS2"],
            "opec_series": ["OPEC.CRUDE_PRODUCTION", "WORLD.CRUDE_PRODUCTION"],
            "worldbank_indicators": ["NY.GDP.MKTP.CD"],
            "comtrade_commodity_codes": ["2709", "2711", "2805"], # Crude, Gas, Metals
            "bea_metrics": ["GDP-Energy"],
            "census_metrics": ["CBP-Energy-Estab"]
        },
        "market_data": {
            "alpha_vantage_symbols": ["XLE", "XOP", "USO", "IYT", "JETS"],
            "frankfurter_fx_pairs": ["USDCAD", "USDNOK", "USDBRL"],
            "instrument_symbols": ["DCOILWTICO", "WPU05", "2709", "2711"]
        },
        "transmission_channels": ["Direct input costs", "Logistics premiums", "Currency volatility in petro-states"],
        "exposure_targets": ["Refiners", "Airlines", "Heavy manufacturing", "Energy-dependent EMs"],
        "watch_indicators": [
            {
                "indicator": "WTI Crude Oil Price",
                "source": "FRED",
                "lookup_type": "external_observation",
                "series_id": "DCOILWTICO",
                "why_it_matters": "Primary global benchmark for oil price sensitivity.",
                "upward_interpretation": "Rising costs for energy consumers, windfall for producers.",
                "downward_interpretation": "Easing headline inflation pressure, risk to exporter fiscal balances.",
                "limitation": "Spot price doesn't reflect long-term contract structures."
            },
            {
                "indicator": "Energy Sector ETF (XLE)",
                "source": "Alpha Vantage",
                "lookup_type": "market_price",
                "symbol": "XLE",
                "why_it_matters": "Direct equity market reflection of energy sector profitability and sentiment.",
                "upward_interpretation": "Market is pricing in sustained demand or margin expansion for energy firms.",
                "downward_interpretation": "Concerns over demand destruction or peak cyclical earnings.",
                "limitation": "XLE is dominated by a few large caps (XOM/CVX)."
            }
        ],
        "balanced_interpretations": {
            "stability_view": "Prices may remain range-bound if inventories compensate for geopolitical friction.",
            "volatility_view": "Low spare capacity makes prices highly sensitive to even minor supply disruptions.",
            "market_confirmation_view": "Check if energy equities (XLE) are leading or lagging the physical price move.",
            "invalidating_conditions": ["Discovery of major new reserves", "Sudden demand destruction"]
        },
        "data_limitations": "Comtrade data has monthly lag; PPI is monthly.",
        "signal_classification_template": {
            "primary_type": "energy_supply_disruption",
            "secondary_types": ["maritime_chokepoint", "petro_fx_sensitivity", "commodity_repricing"],
            "rationale": "Related events point to oil export disruption and tanker route risk rather than a pure demand shock."
        },
        "relevance_map": {
            "DCOILWTICO": "Global crude oil repricing proxy",
            "WCESTUS1": "U.S. crude oil inventories ex-SPR — weekly supply/demand balance",
            "WPULEUS3": "U.S. refinery utilization — operable capacity usage",
            "WCRFPUS2": "U.S. field crude production — domestic supply growth",
            "OPEC.CRUDE_PRODUCTION": "OPEC crude production — cartel supply strategy",
            "WORLD.CRUDE_PRODUCTION": "World crude production — global supply baseline",
            "GASREGW": "Consumer fuel cost pass-through",
            "WPU05": "Upstream producer price pressure for fuels",
            "WPU051": "Refined petroleum product cost index",
            "NY.GDP.MKTP.CD": "Aggregate output exposure to energy costs",
            "XLE": "Energy equity market confirmation",
            "XOP": "Exploration & production equity proxy",
            "USO": "Crude oil futures ETF tracking",
            "IYT": "Transport-sector cost sensitivity",
            "JETS": "Airline fuel-cost pass-through proxy",
            "USDCAD": "Petro-state FX: Canadian dollar sensitivity",
            "USDNOK": "Petro-state FX: Norwegian krone sensitivity",
            "USDBRL": "EM petro-state FX: Brazilian real sensitivity",
            "2709": "Crude petroleum trade volume",
            "2711": "Natural gas trade volume",
            "2805": "Strategic metals trade volume"
        },
        "market_group_map": {
            "XLE": {"group": "Energy Producers", "order": 1},
            "XOP": {"group": "Energy Producers", "order": 1},
            "USO": {"group": "Oil Price Proxy", "order": 2},
            "DCOILWTICO": {"group": "Oil Price Proxy", "order": 2},
            "IYT": {"group": "Transport Sensitivity", "order": 3},
            "JETS": {"group": "Transport Sensitivity", "order": 3},
            "USDCAD": {"group": "Petro FX", "order": 4},
            "USDNOK": {"group": "Petro FX", "order": 4},
            "USDBRL": {"group": "Petro FX", "order": 4}
        },
        "market_group_interpretation": {
            "Energy Producers": {"positive_means": "confirming", "negative_means": "stress", "description": "Rising energy equities confirm supply-side pressure"},
            "Oil Price Proxy": {"positive_means": "confirming", "negative_means": "easing", "description": "Crude price movement validates or contradicts disruption thesis"},
            "Transport Sensitivity": {"positive_means": "resilient", "negative_means": "stress", "description": "Transport weakness under rising energy costs signals cost pass-through pressure"},
            "Petro FX": {"positive_means": "stress", "negative_means": "confirming", "description": "USD strengthening vs petro-currencies indicates capital flow pressure on exporters"}
        },
        "watch_conditions_template": {
            "escalation": [
                {"condition": "WTI and USO rise while IYT/JETS weaken", "monitored_data": ["DCOILWTICO", "USO", "IYT", "JETS"]},
                {"condition": "Additional tanker or port disruption events appear", "monitored_data": ["related_news"]},
                {"condition": "Petro-state FX becomes more volatile", "monitored_data": ["USDCAD", "USDNOK", "USDBRL"]}
            ],
            "deescalation": [
                {"condition": "Crude prices stabilize within 5% band", "monitored_data": ["DCOILWTICO", "USO"]},
                {"condition": "Related shipping / port alerts decline", "monitored_data": ["related_news"]},
                {"condition": "Transport-sensitive assets recover", "monitored_data": ["IYT", "JETS"]}
            ]
        },
        "exposure_matrix_details": [
            {"target": "Refiners", "transmission": "crude input costs", "sensitivity": "high", "reason": "Margins can narrow when crude costs rise faster than refined product prices."},
            {"target": "Airlines", "transmission": "jet fuel procurement", "sensitivity": "high", "reason": "Fuel is the largest variable cost; hedging only delays exposure."},
            {"target": "Heavy manufacturing", "transmission": "energy-intensive processes", "sensitivity": "medium", "reason": "Natural gas and electricity costs flow through to production margins."},
            {"target": "Energy-dependent EMs", "transmission": "import bill / fiscal balance", "sensitivity": "high", "reason": "Oil-importing emerging markets face twin deficits when crude rises sharply."}
        ]
    },
    "global_market_intelligence": {
        "domain_id": "global_market_intelligence",
        "display_name": "Global Market Intelligence",
        "primary_user_question": "How do macroeconomic policy shifts and interest rate cycles alter the global risk-on/risk-off environment?",
        "primary_asset_classes": ["Equity Indices", "Sovereign Bonds", "Safe-haven FX", "Gold", "Volatility Indices"],
        "decision_relevant_questions": [
            "Does the signal indicate a shift in central bank policy expectations (hawkish/dahwish)?",
            "Are we seeing a divergence between economic data and market pricing?",
            "Which asset classes are most sensitive to this liquidity shift?"
        ],
        "structural_data": {
            "fred_series": ["FEDFUNDS", "DGS10", "CPIAUCSL", "DTWEXBGS", "M2SL"],
            "bls_series": ["WPUFD4"], # PPI Final Demand
            "worldbank_indicators": ["NY.GDP.MKTP.KD.ZG", "FP.CPI.TOTL.ZG"], # Growth, Inflation
            "estat_series": ["0003423164"],  # Japan CPI
            "ecb_series": [
                "FM.D.U2.EUR.4F.KR.MRR_FAC.LEV",
                "EXR.D.USD.EUR.SP00.A",
                "ICP.M.U2.N.000000.4.ANR",
            ],
            "bcb_series": ["BCB.11", "BCB.1", "BCB.433"],
            "comtrade_commodity_codes": [],
            "bea_metrics": ["GDP-Total"],
            "census_metrics": []
        },
        "market_data": {
            "alpha_vantage_symbols": ["SPY", "QQQ", "IWM", "TLT", "SHY", "GLD", "USO"],
            "frankfurter_fx_pairs": ["EURUSD", "USDJPY", "GBPUSD", "AUDUSD"],
            "instrument_symbols": ["FEDFUNDS", "DGS10", "CPIAUCSL", "DTWEXBGS"]
        },
        "transmission_channels": ["Cost of capital", "Discount rates for equities", "Cross-border capital flows"],
        "exposure_targets": ["Global banks", "Growth stocks", "Emerging market debt", "Carry trades"],
        "watch_indicators": [
            {
                "indicator": "10-Year Treasury Yield",
                "source": "FRED",
                "lookup_type": "external_observation",
                "series_id": "DGS10",
                "why_it_matters": "Risk-free rate benchmark for global valuation.",
                "upward_interpretation": "Tighter financial conditions, pressure on growth assets.",
                "downward_interpretation": "Looser conditions, supportive of risk assets and duration.",
                "limitation": "Distorted by quantitative easing/tightening and term premia."
            },
            {
                "indicator": "Broad Dollar Index",
                "source": "FRED",
                "lookup_type": "external_observation",
                "series_id": "DTWEXBGS",
                "why_it_matters": "Measures the value of the USD against a broad basket of currencies.",
                "upward_interpretation": "USD strength typically signals global tightening or flight to quality.",
                "downward_interpretation": "USD weakness supports global liquidity and EM risk assets.",
                "limitation": "May be skewed by individual currency crises."
            },
            {
                "indicator": "CPI Inflation (Headline)",
                "source": "FRED",
                "lookup_type": "external_observation",
                "series_id": "CPIAUCSL",
                "why_it_matters": "Primary measure of US consumer price inflation.",
                "upward_interpretation": "Inflationary pressure likely leads to hawkish central bank pivots.",
                "downward_interpretation": "Disinflationary trends support policy easing or normalization.",
                "limitation": "Subject to volatile energy and food components."
            },
            {
                "indicator": "S&P 500 ETF (SPY)",
                "source": "Alpha Vantage",
                "lookup_type": "market_price",
                "symbol": "SPY",
                "why_it_matters": "Broadest benchmark for global risk sentiment and US equity health.",
                "upward_interpretation": "General risk-on environment, supportive of growth and consumption.",
                "downward_interpretation": "Systemic risk aversion or tightening financial conditions.",
                "limitation": "Broad index can hide internal sector rotation."
            }
        ],
        "balanced_interpretations": {
            "stability_view": "Growth may absorb moderate rate hikes if productivity is rising.",
            "volatility_view": "Inverted yield curves signal high risk of structural breaking points.",
            "market_confirmation_view": "Compare DGS10 moves with equity index duration sensitivity (QQQ).",
            "invalidating_conditions": ["Unexpected central bank pivot", "Hyper-inflationary breakout"]
        },
        "data_limitations": "Macro data is backward-looking; market data is leading.",
        "signal_classification_template": {
            "primary_type": "macro_policy_shift",
            "secondary_types": ["rate_cycle_inflection", "liquidity_regime_change", "risk_sentiment_rotation"],
            "rationale": "Signal reflects central bank policy expectations and cross-asset risk repricing rather than sector-specific fundamentals."
        },
        "relevance_map": {
            "FEDFUNDS": "Federal funds rate — overnight borrowing cost benchmark",
            "DGS10": "10-year Treasury yield — long-term discount rate proxy",
            "CPIAUCSL": "Headline CPI — inflation expectation anchor",
            "DTWEXBGS": "Broad USD index — global liquidity pressure gauge",
            "M2SL": "M2 money supply — aggregate liquidity measure",
            "WPUFD4": "PPI Final Demand — upstream inflation pressure",
            "NY.GDP.MKTP.KD.ZG": "Real GDP growth rate",
            "FP.CPI.TOTL.ZG": "Global inflation rate comparison",
            "0003423164": "Japan CPI — domestic inflation and BoJ policy context",
            "FM.D.U2.EUR.4F.KR.MRR_FAC.LEV": "ECB main refinancing rate — euro area policy stance",
            "EXR.D.USD.EUR.SP00.A": "EUR/USD reference rate — transatlantic FX and liquidity",
            "ICP.M.U2.N.000000.4.ANR": "Euro area HICP — ECB inflation mandate anchor",
            "BCB.11": "Brazil Selic — EM policy rate and risk appetite",
            "BCB.1": "Brazil USD/BRL — EM FX and commodity export sensitivity",
            "BCB.433": "Brazil IPCA — EM inflation pass-through",
            "SPY": "S&P 500 — broad risk sentiment",
            "QQQ": "Nasdaq 100 — growth/duration sensitivity",
            "IWM": "Russell 2000 — domestic cyclical proxy",
            "TLT": "Long-duration Treasury ETF — rate sensitivity",
            "SHY": "Short-duration Treasury — front-end rate expectations",
            "GLD": "Gold — real rate and safe-haven proxy",
            "USO": "Crude oil — inflation input component",
            "EURUSD": "Euro/USD — transatlantic policy divergence",
            "USDJPY": "USD/JPY — carry trade and BoJ policy proxy",
            "GBPUSD": "GBP/USD — UK macro sensitivity",
            "AUDUSD": "AUD/USD — commodity and China growth proxy"
        },
        "market_group_map": {
            "SPY": {"group": "Equity Indices", "order": 1},
            "QQQ": {"group": "Equity Indices", "order": 1},
            "IWM": {"group": "Equity Indices", "order": 1},
            "TLT": {"group": "Fixed Income", "order": 2},
            "SHY": {"group": "Fixed Income", "order": 2},
            "GLD": {"group": "Safe Haven", "order": 3},
            "USO": {"group": "Commodities", "order": 4},
            "EURUSD": {"group": "FX Majors", "order": 5},
            "USDJPY": {"group": "FX Majors", "order": 5},
            "GBPUSD": {"group": "FX Majors", "order": 5},
            "AUDUSD": {"group": "FX Majors", "order": 5}
        },
        "market_group_interpretation": {
            "Equity Indices": {"positive_means": "risk_on", "negative_means": "stress", "description": "Broad equity direction reflects macro risk appetite"},
            "Fixed Income": {"positive_means": "flight_to_safety", "negative_means": "risk_on", "description": "Bond prices rising suggests rate cut expectations or risk aversion"},
            "Safe Haven": {"positive_means": "stress", "negative_means": "risk_on", "description": "Gold rising signals real-rate or geopolitical anxiety"},
            "Commodities": {"positive_means": "inflationary", "negative_means": "deflationary", "description": "Commodity prices reflect inflation expectations"},
            "FX Majors": {"positive_means": "usd_strength", "negative_means": "usd_weakness", "description": "FX pairs indicate USD liquidity conditions"}
        },
        "watch_conditions_template": {
            "escalation": [
                {"condition": "Yield curve inversion deepens while equities fall", "monitored_data": ["DGS10", "FEDFUNDS", "SPY"]},
                {"condition": "USD strengthens rapidly against EM currencies", "monitored_data": ["DTWEXBGS"]},
                {"condition": "Gold and TLT rise simultaneously (flight to safety)", "monitored_data": ["GLD", "TLT"]}
            ],
            "deescalation": [
                {"condition": "Yield curve normalizes; equity vol subsides", "monitored_data": ["DGS10", "SPY"]},
                {"condition": "Fed guidance turns dovish or neutral", "monitored_data": ["FEDFUNDS"]},
                {"condition": "EM FX stabilizes; capital outflows slow", "monitored_data": ["DTWEXBGS", "AUDUSD"]}
            ]
        },
        "exposure_matrix_details": [
            {"target": "Global banks", "transmission": "net interest margins and credit risk", "sensitivity": "high", "reason": "Rate changes directly impact lending profitability and loan loss provisions."},
            {"target": "Growth stocks", "transmission": "discount rate sensitivity", "sensitivity": "high", "reason": "Long-duration equity valuations compress when risk-free rates rise."},
            {"target": "Emerging market debt", "transmission": "USD-denominated borrowing costs", "sensitivity": "high", "reason": "Stronger USD and higher US rates increase EM debt service burdens."},
            {"target": "Carry trades", "transmission": "interest rate differential", "sensitivity": "medium", "reason": "Narrowing differentials unwind leveraged FX positions."}
        ]
    },
    "ai_semiconductor_intelligence": {
        "domain_id": "ai_semiconductor_intelligence",
        "display_name": "AI & Semiconductor Intelligence",
        "primary_user_question": "How do export controls and technological bottlenecks in the AI/Semi supply chain impact sectoral growth and national security?",
        "primary_asset_classes": ["Semi Equities", "Big Tech", "AI Infrastructure", "Tech-sensitive FX"],
        "decision_relevant_questions": [
            "Is the bottleneck at the foundry (TSMC), equipment (ASML), or design (NVIDIA) level?",
            "Do export control changes align with trade flow shifts?",
            "Are market valuations reflecting physical capacity constraints?"
        ],
        "structural_data": {
            "fred_series": ["IPB53122S", "DGS10"], # Semi Production, Rates
            "bls_series": ["PCU334413334413"], # PPI Semi
            "worldbank_indicators": [],
            "estat_series": ["0003410537"],  # Japan IIP (mining & manufacturing)
            "comtrade_commodity_codes": ["8542"], # Integrated circuits
            "bea_metrics": ["Value-Added-Manufacturing"],
            "census_metrics": ["CBP-Semi-Estab"],
            "industry_keywords": ["Manufacturing", "Computer and electronic products", "Information", "Data processing", "Professional/scientific/technical services", "Electrical equipment"]
        },
        "market_data": {
            "alpha_vantage_symbols": ["SMH", "SOXX", "QQQ", "EWJ", "EWY"],
            "frankfurter_fx_pairs": ["USDJPY", "USDKRW", "USDTWD"],
            "instrument_symbols": ["8542", "DGS10", "DTWEXBGS"]
        },
        "transmission_channels": ["CapEx cycles", "Export license approvals", "Geopolitical foundry concentration"],
        "exposure_targets": ["Cloud providers", "Chip designers", "WFE manufacturers", "Device OEMs"],
        "watch_indicators": [
            {
                "indicator": "IC Trade Volume",
                "source": "Comtrade",
                "lookup_type": "trade_flow",
                "symbol": "8542",
                "why_it_matters": "Direct measure of global semiconductor supply chain activity.",
                "upward_interpretation": "Robust global tech demand and easing trade friction.",
                "downward_interpretation": "Inventory digestion or impact of trade restrictions.",
                "limitation": "Customs data has significant reporting lag."
            },
            {
                "indicator": "Semiconductor PPI",
                "source": "BLS",
                "lookup_type": "external_observation",
                "series_id": "PCU334413334413",
                "why_it_matters": "Measures price pressure in semiconductor manufacturing.",
                "upward_interpretation": "Rising input costs or strong pricing power due to scarcity.",
                "downward_interpretation": "Easing capacity constraints or demand softening.",
                "limitation": "Reflects US-based production costs primarily."
            },
            {
                "indicator": "10-Year Treasury Yield",
                "source": "FRED",
                "lookup_type": "external_observation",
                "series_id": "DGS10",
                "why_it_matters": "Tech valuations are highly sensitive to long-term discount rates.",
                "upward_interpretation": "Pressure on high-growth tech valuations.",
                "downward_interpretation": "Supportive environment for tech valuation expansion.",
                "limitation": "Yield moves can also reflect growth expectations, not just inflation."
            },
            {
                "indicator": "Semiconductor ETF (SMH)",
                "source": "Alpha Vantage",
                "lookup_type": "market_price",
                "symbol": "SMH",
                "why_it_matters": "Primary proxy for global semiconductor equity sentiment and AI demand.",
                "upward_interpretation": "Market confirmation of robust structural growth in AI/Semi.",
                "downward_interpretation": "Corrective cycle or reflection of overcapacity/trade risk.",
                "limitation": "High concentration in top names like NVIDIA and TSMC."
            }
        ],
        "balanced_interpretations": {
            "stability_view": "Diversification of foundry locations may stabilize long-term supply.",
            "volatility_view": "Extreme concentration in Taiwan makes the entire sector a geopolitical binary.",
            "market_confirmation_view": "Watch if SMH performance diverges from Comtrade trade value trends.",
            "invalidating_conditions": ["Breakthrough in non-silicon computing", "Peaceful tech de-escalation"]
        },
        "data_limitations": "Trade data lag is the primary challenge for real-time analysis.",
        "signal_classification_template": {
            "primary_type": "tech_supply_chain_disruption",
            "secondary_types": ["export_control_shift", "foundry_concentration_risk", "capex_cycle_inflection"],
            "rationale": "Signal relates to semiconductor manufacturing constraints or trade policy changes affecting chip supply chains."
        },
        "relevance_map": {
            "IPB53122S": "US semiconductor industrial production index",
            "DGS10": "Long-term discount rate — tech valuation sensitivity",
            "PCU334413334413": "PPI for semiconductor manufacturing",
            "0003410537": "Japan IIP — manufacturing output cycle (semi supply chain)",
            "8542": "Integrated circuit global trade volume",
            "SMH": "Semiconductor equity ETF — sector sentiment",
            "SOXX": "Broad semiconductor index — confirmation",
            "QQQ": "Nasdaq 100 — tech beta proxy",
            "EWJ": "Japan equities — equipment maker exposure",
            "EWY": "South Korea equities — memory/foundry exposure",
            "USDJPY": "JPY sensitivity to tech export cycles",
            "USDKRW": "KRW sensitivity to semiconductor exports",
            "USDTWD": "TWD sensitivity to foundry revenue concentration"
        },
        "market_group_map": {
            "SMH": {"group": "Semiconductor Equities", "order": 1},
            "SOXX": {"group": "Semiconductor Equities", "order": 1},
            "QQQ": {"group": "Tech Beta", "order": 2},
            "EWJ": {"group": "Asia Tech Exposure", "order": 3},
            "EWY": {"group": "Asia Tech Exposure", "order": 3},
            "USDJPY": {"group": "Tech-Sensitive FX", "order": 4},
            "USDKRW": {"group": "Tech-Sensitive FX", "order": 4},
            "USDTWD": {"group": "Tech-Sensitive FX", "order": 4}
        },
        "market_group_interpretation": {
            "Semiconductor Equities": {"positive_means": "confirming", "negative_means": "stress", "description": "Chip sector equities reflect supply chain confidence"},
            "Tech Beta": {"positive_means": "risk_on", "negative_means": "stress", "description": "Broad tech sentiment proxy"},
            "Asia Tech Exposure": {"positive_means": "confirming", "negative_means": "stress", "description": "Asia foundry/equipment exposure"},
            "Tech-Sensitive FX": {"positive_means": "stress", "negative_means": "confirming", "description": "USD strengthening vs Asian tech currencies signals export revenue risk"}
        },
        "watch_conditions_template": {
            "escalation": [
                {"condition": "SMH falls while trade restriction headlines increase", "monitored_data": ["SMH", "related_news"]},
                {"condition": "TWD or KRW weaken sharply (foundry revenue risk)", "monitored_data": ["USDTWD", "USDKRW"]},
                {"condition": "IC trade volumes decline in Comtrade data", "monitored_data": ["8542"]}
            ],
            "deescalation": [
                {"condition": "Export license approvals resume or expand", "monitored_data": ["related_news"]},
                {"condition": "SMH and SOXX recover toward 52-week highs", "monitored_data": ["SMH", "SOXX"]},
                {"condition": "Foundry utilization stabilizes above 80%", "monitored_data": ["IPB53122S"]}
            ]
        },
        "exposure_matrix_details": [
            {"target": "Cloud providers", "transmission": "GPU procurement costs and lead times", "sensitivity": "high", "reason": "AI training infrastructure depends on leading-edge chip availability."},
            {"target": "Chip designers", "transmission": "foundry access and pricing", "sensitivity": "high", "reason": "Fabless firms are fully dependent on TSMC/Samsung capacity allocation."},
            {"target": "WFE manufacturers", "transmission": "order backlog volatility", "sensitivity": "medium", "reason": "Equipment demand follows cyclical CapEx patterns with long lead times."},
            {"target": "Device OEMs", "transmission": "component availability and BOM costs", "sensitivity": "medium", "reason": "Consumer electronics margins compress when chip costs rise or supply tightens."}
        ]
    },
    "defense_technology": {
        "domain_id": "defense_technology",
        "display_name": "Defense Technology",
        "primary_user_question": "How do shifts in defense spending and aerospace trade flows reflect changing geopolitical alignments?",
        "primary_asset_classes": ["Defense Contractors", "Aerospace Equities", "Rare Earth Metals"],
        "decision_relevant_questions": [
            "Does a spending surge correlate with specific regional conflict risks?",
            "Are supply chains for critical defense materials (rare earths) shifting?",
            "Are procurement cycles accelerating relative to historical averages?"
        ],
        "structural_data": {
            "fred_series": ["FDEFX"], # Federal Defense Spending
            "bls_series": ["PCU336411336411"], # PPI Aircraft
            "worldbank_indicators": ["MS.MIL.XPND.GD.ZS"], # Military spend % GDP
            "comtrade_commodity_codes": ["8802", "8906", "9301", "2805"], # Aircraft, Warships, Arms, Metals
            "bea_metrics": ["GDP-Defense"],
            "census_metrics": ["CBP-Defense-Estab"],
            "industry_keywords": [
                "Government", "Manufacturing", "Aerospace", "Aircraft", 
                "Transportation equipment", "Machinery", "Electrical equipment", 
                "Computer and electronic products", "Metals", "Mining", 
                "Professional and technical services"
            ]
        },
        "market_data": {
            "alpha_vantage_symbols": ["ITA", "XAR", "PPA", "XLI"],
            "frankfurter_fx_pairs": ["USDJPY", "EURUSD"],
            "instrument_symbols": ["8802", "8906", "9301", "2805"]
        },
        "transmission_channels": ["Government budget cycles", "FMS (Foreign Military Sales) approvals", "Critical material availability"],
        "exposure_targets": ["Prime contractors", "Sub-tier suppliers", "Cyber-defense firms", "Materials miners"],
        "watch_indicators": [
            {
                "indicator": "Aerospace & Defense ETF (ITA)",
                "source": "Alpha Vantage",
                "lookup_type": "market_price",
                "symbol": "ITA",
                "why_it_matters": "Market reflection of defense spending cycles and geopolitical risk premiums.",
                "upward_interpretation": "Market is pricing in increased procurement or elevated security risk.",
                "downward_interpretation": "Budgetary pivot or de-escalation of regional tensions.",
                "limitation": "Includes commercial aerospace (Boeing), which can skew defense signals."
            },
            {
                "indicator": "Federal Defense Spending",
                "source": "FRED",
                "lookup_type": "external_observation",
                "series_id": "FDEFX",
                "why_it_matters": "Direct measure of US government defense procurement and operational outlays.",
                "upward_interpretation": "Expansionary defense budget, supportive of contractor backlogs.",
                "downward_interpretation": "Fiscal tightening or shift in national security priorities.",
                "limitation": "Quarterly reporting with significant lag."
            },
            {
                "indicator": "Aerospace Trade Flow (8802)",
                "source": "Comtrade",
                "lookup_type": "trade_flow",
                "symbol": "8802",
                "why_it_matters": "Proxy for global defense and strategic aerospace shifts.",
                "upward_interpretation": "Increasing regional security alliances and fleet modernization.",
                "downward_interpretation": "Budgetary constraints or shift to indigenous production.",
                "limitation": "Sensitive data may be classified or obfuscated in public trade stats."
            },
            {
                "indicator": "Industrial Sector ETF (XLI)",
                "source": "Alpha Vantage",
                "lookup_type": "market_price",
                "symbol": "XLI",
                "why_it_matters": "Measures the health of the broader industrial base supporting defense manufacturing.",
                "upward_interpretation": "Robust industrial capacity and manufacturing growth.",
                "downward_interpretation": "Industrial slowdown impacting sub-tier defense suppliers.",
                "limitation": "Broad exposure to non-defense cyclical industrials."
            }
        ],
        "balanced_interpretations": {
            "stability_view": "Long-term contracts provide earnings visibility despite short-term volatility.",
            "volatility_view": "Sudden policy shifts or 'peace dividends' can rapidly de-rate the sector.",
            "market_confirmation_view": "Correlation between ITA/XAR and Comtrade HS8802 export volumes.",
            "invalidating_conditions": ["Global disarmament treaty", "Drastic shift in warfighting technology (e.g. drones replacing manned jets)"]
        },
        "data_limitations": "Defense data is often intentionally delayed or aggregated.",
        "signal_classification_template": {
            "primary_type": "defense_procurement_shift",
            "secondary_types": ["geopolitical_alliance_realignment", "arms_trade_expansion", "critical_material_dependency"],
            "rationale": "Signal reflects changes in defense spending patterns, arms trade corridors, or strategic material supply chains."
        },
        "relevance_map": {
            "FDEFX": "Federal defense expenditure — procurement cycle gauge",
            "PCU336411336411": "PPI for aircraft manufacturing",
            "MS.MIL.XPND.GD.ZS": "Military expenditure as % of GDP — global comparison",
            "8802": "Aircraft trade flows — strategic aerospace transfers",
            "8906": "Warship trade — naval power projection indicator",
            "9301": "Arms and ammunition trade volume",
            "2805": "Strategic metals — critical material dependency",
            "ITA": "Aerospace & Defense ETF — sector sentiment",
            "XAR": "S&P Aerospace & Defense ETF — confirmation",
            "PPA": "Invesco Aerospace & Defense — sub-tier exposure",
            "XLI": "Industrial sector — defense manufacturing base health",
            "USDJPY": "USD/JPY — security alliance FX proxy",
            "EURUSD": "EUR/USD — NATO spending divergence"
        },
        "market_group_map": {
            "ITA": {"group": "Defense Equities", "order": 1},
            "XAR": {"group": "Defense Equities", "order": 1},
            "PPA": {"group": "Defense Equities", "order": 1},
            "XLI": {"group": "Industrial Base", "order": 2},
            "USDJPY": {"group": "Alliance FX", "order": 3},
            "EURUSD": {"group": "Alliance FX", "order": 3}
        },
        "market_group_interpretation": {
            "Defense Equities": {"positive_means": "confirming", "negative_means": "easing", "description": "Defense sector equities reflect procurement outlook"},
            "Industrial Base": {"positive_means": "confirming", "negative_means": "stress", "description": "Manufacturing base health signals defense production capacity"},
            "Alliance FX": {"positive_means": "usd_strength", "negative_means": "usd_weakness", "description": "Alliance currency dynamics"}
        },
        "watch_conditions_template": {
            "escalation": [
                {"condition": "Defense ETFs (ITA/XAR) rise on elevated conflict headlines", "monitored_data": ["ITA", "XAR", "related_news"]},
                {"condition": "Rare earth or strategic metal trade volumes shift", "monitored_data": ["2805"]},
                {"condition": "Federal defense spending accelerates quarter-over-quarter", "monitored_data": ["FDEFX"]}
            ],
            "deescalation": [
                {"condition": "Diplomatic resolution reduces procurement urgency", "monitored_data": ["related_news"]},
                {"condition": "Defense ETFs consolidate while industrial base (XLI) strengthens", "monitored_data": ["ITA", "XLI"]},
                {"condition": "Arms trade volumes plateau in Comtrade data", "monitored_data": ["9301", "8802"]}
            ]
        },
        "exposure_matrix_details": [
            {"target": "Prime contractors", "transmission": "government contract awards", "sensitivity": "high", "reason": "Revenue visibility tied directly to multi-year procurement programs."},
            {"target": "Sub-tier suppliers", "transmission": "component demand from primes", "sensitivity": "medium", "reason": "Smaller suppliers face concentration risk and slower payment cycles."},
            {"target": "Cyber-defense firms", "transmission": "digital threat escalation", "sensitivity": "medium", "reason": "Cyber budgets expand when threat environments elevate."},
            {"target": "Materials miners", "transmission": "rare earth and strategic metal demand", "sensitivity": "high", "reason": "Defense modernization increases demand for specialized alloys and rare earths."}
        ]
    },
    "supply_chain_intelligence": {
        "domain_id": "supply_chain_intelligence",
        "display_name": "Supply Chain Intelligence",
        "primary_user_question": "How do logistics bottlenecks and critical material dependencies affect global industrial output?",
        "primary_asset_classes": ["Logistics Equities", "Industrial ETFs", "Base Metals", "Transport-sensitive FX"],
        "decision_relevant_questions": [
            "Is the disruption caused by labor, physical infrastructure, or policy?",
            "Are we seeing near-shoring or friend-shoring in the trade data?",
            "Do transport costs align with PPI industrial input trends?"
        ],
        "structural_data": {
            "fred_series": ["IPI", "PCU484111484111"], # Industrial Production, Trucking
            "bls_series": ["WPU101", "WPU10"], # PPI Metals, PPI Industrial materials
            "worldbank_indicators": ["IS.SHP.GCNW.XQ"], # LPI
            "comtrade_commodity_codes": ["2805", "8507", "8703"], # Metals, Batteries, Vehicles
            "asean_series": ["FDI.AMS.TOT.INF", "IMTS.Annually"],
            "bea_metrics": ["Value-Added-Manufacturing"],
            "census_metrics": ["CBP-Manufacturing-Estab"]
        },
        "market_data": {
            "alpha_vantage_symbols": ["XLI", "IYT", "XLB", "CARZ", "XLE"],
            "frankfurter_fx_pairs": ["USDKRW", "USDSGD", "USDCNY", "USDJPY"],
            "instrument_symbols": ["2805", "8507", "WPU101"]
        },
        "transmission_channels": ["Freight rates", "Inventory-to-sales ratios", "Regional trade agreement shifts"],
        "exposure_targets": ["Global retailers", "Automakers", "Freight forwarders", "Industrial conglomerates"],
        "industry_keywords": [
            "Manufacturing", "Transportation", "Warehousing", "Wholesale trade", 
            "Retail trade", "Motor vehicles", "Electrical equipment", 
            "Machinery", "Materials", "Mining"
        ],
        "watch_indicators": [
            {
                "indicator": "PPI Industrial Metals",
                "source": "BLS",
                "lookup_type": "external_observation",
                "series_id": "WPU101",
                "why_it_matters": "Measures price pressure in raw metal inputs for manufacturing.",
                "upward_interpretation": "Rising input costs for heavy industry and construction.",
                "downward_interpretation": "Easing material cost pressure, potential demand softening.",
                "limitation": "Global prices may diverge from US PPI based on local availability."
            },
            {
                "indicator": "Strategic Mineral Trade (2805)",
                "source": "Comtrade",
                "lookup_type": "trade_flow",
                "symbol": "2805",
                "why_it_matters": "Tracks global trade of alkali metals and rare earth elements.",
                "upward_interpretation": "Increasing strategic stockpiling or robust high-tech manufacturing demand.",
                "downward_interpretation": "Trade friction or slowing industrial output in key markets.",
                "limitation": "Heavily influenced by China's export quotas."
            },
            {
                "indicator": "Industrial Sector ETF (XLI)",
                "source": "Alpha Vantage",
                "lookup_type": "market_price",
                "symbol": "XLI",
                "why_it_matters": "Broadest proxy for US industrial and manufacturing sector health.",
                "upward_interpretation": "Market expectation of industrial expansion and CapEx growth.",
                "downward_interpretation": "Fear of cyclical downturn or supply chain bottlenecks impacting margins.",
                "limitation": "Large components are global conglomerates with diversified exposure."
            },
            {
                "indicator": "Transportation ETF (IYT)",
                "source": "Alpha Vantage",
                "lookup_type": "market_price",
                "symbol": "IYT",
                "why_it_matters": "The 'Dow Theory' indicator for physical economic activity and logistics health.",
                "upward_interpretation": "Robust goods movement and healthy consumption trends.",
                "downward_interpretation": "Logistics overcapacity or early warning of industrial slowdown.",
                "limitation": "Sensitive to fuel prices and labor cost shocks independently of volume."
            }
        ],
        "balanced_interpretations": {
            "stability_view": "Automation and reshoring may reduce long-tail supply chain risks.",
            "volatility_view": "Just-in-time models remain vulnerable to multi-nodal failure.",
            "market_confirmation_view": "Check IYT (Transports) against PPI Trucking and Comtrade HS8703 data.",
            "invalidating_conditions": ["Widespread adoption of localized 3D printing", "End of global trade-led growth"]
        },
        "data_limitations": "Comtrade data for complex goods (HS8703) is highly fragmented.",
        "signal_classification_template": {
            "primary_type": "logistics_bottleneck",
            "secondary_types": ["nearshoring_shift", "critical_material_shortage", "freight_rate_disruption"],
            "rationale": "Signal indicates physical supply chain disruption through logistics constraints, material shortages, or trade corridor shifts."
        },
        "relevance_map": {
            "IPI": "US industrial production index — output health",
            "PCU484111484111": "PPI for trucking — freight cost pressure",
            "WPU101": "PPI metals — raw material input costs",
            "WPU10": "PPI industrial materials — broad input costs",
            "IS.SHP.GCNW.XQ": "Logistics Performance Index — infrastructure quality",
            "2805": "Strategic metals trade — critical material flow",
            "8507": "Battery trade — EV and energy storage supply",
            "8703": "Vehicle trade — automotive supply chain proxy",
            "XLI": "Industrial sector ETF — manufacturing health",
            "IYT": "Transportation ETF — logistics sentiment",
            "XLB": "Materials ETF — input cost proxy",
            "CARZ": "Automotive ETF — end-market demand",
            "XLE": "Energy ETF — fuel cost for logistics",
            "USDKRW": "KRW — Asian manufacturing proxy",
            "USDSGD": "SGD — trade hub sensitivity",
            "USDCNY": "CNY — China factory output proxy",
            "USDJPY": "JPY — Japanese industrial export sensitivity",
            "FDI.AMS.TOT.INF": "ASEAN total FDI — regional investment and supply-chain capex",
            "IMTS.Annually": "ASEAN merchandise trade — intra-bloc goods flow"
        },
        "market_group_map": {
            "XLI": {"group": "Industrial Production", "order": 1},
            "IYT": {"group": "Transport & Logistics", "order": 2},
            "XLB": {"group": "Materials & Inputs", "order": 3},
            "CARZ": {"group": "End-Market Demand", "order": 4},
            "XLE": {"group": "Fuel & Energy Costs", "order": 5},
            "USDKRW": {"group": "Asia Manufacturing FX", "order": 6},
            "USDSGD": {"group": "Asia Manufacturing FX", "order": 6},
            "USDCNY": {"group": "Asia Manufacturing FX", "order": 6},
            "USDJPY": {"group": "Asia Manufacturing FX", "order": 6}
        },
        "market_group_interpretation": {
            "Industrial Production": {"positive_means": "resilient", "negative_means": "stress", "description": "Industrial output health"},
            "Transport & Logistics": {"positive_means": "resilient", "negative_means": "stress", "description": "Logistics capacity and pricing"},
            "Materials & Inputs": {"positive_means": "inflationary", "negative_means": "easing", "description": "Input cost trajectory"},
            "End-Market Demand": {"positive_means": "confirming", "negative_means": "stress", "description": "Consumer and OEM demand signals"},
            "Fuel & Energy Costs": {"positive_means": "stress", "negative_means": "easing", "description": "Logistics energy cost pressure"},
            "Asia Manufacturing FX": {"positive_means": "stress", "negative_means": "confirming", "description": "USD vs Asian manufacturing currencies"}
        },
        "watch_conditions_template": {
            "escalation": [
                {"condition": "IYT weakens while freight PPI rises", "monitored_data": ["IYT", "PCU484111484111"]},
                {"condition": "Metals PPI spikes with declining Comtrade volumes", "monitored_data": ["WPU101", "2805"]},
                {"condition": "Additional port or route disruption events appear", "monitored_data": ["related_news"]}
            ],
            "deescalation": [
                {"condition": "Freight rates normalize; IYT recovers", "monitored_data": ["IYT", "PCU484111484111"]},
                {"condition": "Trade volumes for critical materials stabilize", "monitored_data": ["2805", "8507"]},
                {"condition": "Industrial production index rebounds", "monitored_data": ["IPI"]}
            ]
        },
        "exposure_matrix_details": [
            {"target": "Global retailers", "transmission": "inventory replenishment lead times", "sensitivity": "high", "reason": "Lean inventory models amplify even short shipping delays into stockouts."},
            {"target": "Automakers", "transmission": "just-in-time component delivery", "sensitivity": "high", "reason": "Single-source dependencies in chips and batteries create cascading production halts."},
            {"target": "Freight forwarders", "transmission": "route availability and pricing", "sensitivity": "medium", "reason": "Margin volatility increases when alternative routes must be sourced quickly."},
            {"target": "Industrial conglomerates", "transmission": "multi-tier supplier networks", "sensitivity": "medium", "reason": "Complex BOM dependencies mean disruptions propagate non-linearly through supply tiers."}
        ]
    },
    "crypto_geopolitics": {
        "domain_id": "crypto_geopolitics",
        "display_name": "Crypto Geopolitics",
        "primary_user_question": "How does digital asset adoption interact with monetary sovereignty and global sanctions evasion?",
        "primary_asset_classes": ["Bitcoin", "Ethereum", "Crypto Equities", "USD Index", "M2 Money Supply"],
        "decision_relevant_questions": [
            "Does crypto price action correlate with traditional 'safe haven' or 'risk' assets?",
            "Are we seeing adoption spikes in regions with high inflation or capital controls?",
            "How do regulatory shifts in major economies impact global liquidity?"
        ],
        "structural_data": {
            "fred_series": ["M2SL", "DTWEXBGS", "DGS10"], # Money Supply, USD Index, Rates
            "bls_series": [],
            "worldbank_indicators": ["FS.AST.DOMS.GD.ZS"], # Domestic credit to private sector
            "comtrade_commodity_codes": [],
            "bea_metrics": [],
            "census_metrics": [],
            "industry_keywords": [
                "Finance", "Insurance", "Information", "Data processing", 
                "Professional, scientific, and technical services", 
                "Computer and electronic products"
            ]
        },
        "market_data": {
            "alpha_vantage_symbols": ["BTC", "ETH", "QQQ", "SPY", "TLT"],
            "frankfurter_fx_pairs": ["USDJPY", "EURUSD", "USDCNY"],
            "instrument_symbols": ["DTWEXBGS", "M2SL"]
        },
        "transmission_channels": ["Global liquidity (M2)", "USD strength/weakness", "Capital control enforcement"],
        "exposure_targets": ["Exchanges", "Miners", "DeFi protocols", "Fintech companies"],
        "watch_indicators": [
            {
                "indicator": "Bitcoin (BTC)",
                "source": "Alpha Vantage",
                "lookup_type": "market_price",
                "symbol": "BTC",
                "why_it_matters": "Leading non-sovereign asset reflecting global liquidity and censorship-resistance premiums.",
                "upward_interpretation": "Expansionary monetary environment or hedging against fiat instability.",
                "downward_interpretation": "Liquidity contraction or regulatory tightening in major fiat ramps.",
                "limitation": "Extremely high volatility and decoupling from macro fundamentals possible."
            },
            {
                "indicator": "Ethereum (ETH)",
                "source": "Alpha Vantage",
                "lookup_type": "market_price",
                "symbol": "ETH",
                "why_it_matters": "Primary smart-contract platform, proxy for decentralized finance (DeFi) activity.",
                "upward_interpretation": "Increased network utility and on-chain capital formation.",
                "downward_interpretation": "Regulatory headwinds for DeFi or technical scalability concerns.",
                "limitation": "Price is sensitive to network upgrade cycles (e.g. Merge, Danksharding)."
            },
            {
                "indicator": "Broad Dollar Index",
                "source": "FRED",
                "lookup_type": "external_observation",
                "series_id": "DTWEXBGS",
                "why_it_matters": "Measures the value of the USD against a broad basket of currencies.",
                "upward_interpretation": "USD strength typically signals global tightening, creating headwinds for crypto.",
                "downward_interpretation": "USD weakness supports global liquidity and speculative assets.",
                "limitation": "May be skewed by individual currency crises."
            },
            {
                "indicator": "M2 Money Supply Growth",
                "source": "FRED",
                "lookup_type": "external_observation",
                "series_id": "M2SL",
                "why_it_matters": "Macro liquidity driver for non-sovereign digital assets.",
                "upward_interpretation": "Debasement risk favoring hard/digital assets.",
                "downward_interpretation": "Liquidity withdrawal, headwinds for speculative assets.",
                "limitation": "M2 velocity and private credit creation also matter."
            },
            {
                "indicator": "Nasdaq 100 ETF (QQQ)",
                "source": "Alpha Vantage",
                "lookup_type": "market_price",
                "symbol": "QQQ",
                "why_it_matters": "Proxy for high-growth risk assets; highly correlated with digital assets.",
                "upward_interpretation": "Bullish risk sentiment favoring technology and growth sectors.",
                "downward_interpretation": "Risk-off environment, typically leading to crypto liquidations.",
                "limitation": "Tech earnings can decouple from macro-driven crypto moves."
            }
        ],
        "balanced_interpretations": {
            "stability_view": "Institutional adoption may lead to lower volatility and correlation with macro.",
            "volatility_view": "Regulatory crackdowns can cause rapid, non-linear liquidity exits.",
            "market_confirmation_view": "Monitor BTC/ETH correlation with QQQ and M2SL trends.",
            "invalidating_conditions": ["Coordinated global ban on crypto-fiat onramps", "Failure of core cryptographic protocols"]
        },
        "data_limitations": "On-chain data is more real-time but not yet integrated; relying on macro proxies.",
        "signal_classification_template": {
            "primary_type": "crypto_regulatory_shift",
            "secondary_types": ["liquidity_regime_change", "sanctions_evasion_vector", "digital_sovereignty_push"],
            "rationale": "Signal relates to regulatory posture changes, monetary policy impacts on digital assets, or sovereign digital currency developments."
        },
        "relevance_map": {
            "M2SL": "M2 money supply — macro liquidity driver for digital assets",
            "DTWEXBGS": "Broad USD index — inverse correlation with crypto risk appetite",
            "DGS10": "10-year yield — opportunity cost of holding non-yielding assets",
            "FS.AST.DOMS.GD.ZS": "Domestic credit to private sector — financial system depth",
            "BTC": "Bitcoin — leading non-sovereign asset",
            "ETH": "Ethereum — DeFi and smart-contract utility proxy",
            "QQQ": "Nasdaq 100 — high-beta risk correlation",
            "SPY": "S&P 500 — broad risk sentiment",
            "TLT": "Long-duration bonds — inverse risk proxy",
            "USDJPY": "USD/JPY — carry trade unwind proxy",
            "EURUSD": "EUR/USD — transatlantic regulatory divergence",
            "USDCNY": "USD/CNY — capital control and CBDC proxy"
        },
        "market_group_map": {
            "BTC": {"group": "Digital Assets", "order": 1},
            "ETH": {"group": "Digital Assets", "order": 1},
            "QQQ": {"group": "Correlated Risk Assets", "order": 2},
            "SPY": {"group": "Correlated Risk Assets", "order": 2},
            "TLT": {"group": "Rate Sensitivity", "order": 3},
            "USDJPY": {"group": "FX / Liquidity", "order": 4},
            "EURUSD": {"group": "FX / Liquidity", "order": 4},
            "USDCNY": {"group": "FX / Liquidity", "order": 4}
        },
        "market_group_interpretation": {
            "Digital Assets": {"positive_means": "confirming", "negative_means": "stress", "description": "Core crypto asset price direction"},
            "Correlated Risk Assets": {"positive_means": "risk_on", "negative_means": "stress", "description": "Broad equity risk appetite correlation"},
            "Rate Sensitivity": {"positive_means": "flight_to_safety", "negative_means": "risk_on", "description": "Duration sensitivity to rate expectations"},
            "FX / Liquidity": {"positive_means": "usd_strength", "negative_means": "usd_weakness", "description": "USD liquidity and capital flow dynamics"}
        },
        "watch_conditions_template": {
            "escalation": [
                {"condition": "BTC and ETH fall while USD strengthens", "monitored_data": ["BTC", "ETH", "DTWEXBGS"]},
                {"condition": "Major exchange regulatory enforcement actions reported", "monitored_data": ["related_news"]},
                {"condition": "M2 growth decelerates while yields rise", "monitored_data": ["M2SL", "DGS10"]}
            ],
            "deescalation": [
                {"condition": "Regulatory clarity (ETF approvals, licensing frameworks) emerges", "monitored_data": ["related_news"]},
                {"condition": "M2 growth reaccelerates; USD softens", "monitored_data": ["M2SL", "DTWEXBGS"]},
                {"condition": "BTC reclaims key moving averages with volume", "monitored_data": ["BTC"]}
            ]
        },
        "exposure_matrix_details": [
            {"target": "Exchanges", "transmission": "regulatory licensing and compliance costs", "sensitivity": "high", "reason": "Operating licenses can be revoked or restricted, directly impacting revenue."},
            {"target": "Miners", "transmission": "energy costs and regulatory bans", "sensitivity": "high", "reason": "Mining profitability depends on electricity costs and jurisdictional legality."},
            {"target": "DeFi protocols", "transmission": "smart contract regulatory classification", "sensitivity": "medium", "reason": "Securities law interpretations can force protocol redesigns or shutdowns."},
            {"target": "Fintech companies", "transmission": "fiat on/off-ramp access", "sensitivity": "medium", "reason": "Banking partner relationships determine ability to serve crypto customers."}
        ]
    }
}

def get_pro_domain_config(domain_id: str) -> Optional[dict]:
    """Retrieve configuration for a specific domain."""
    return PRO_DOMAIN_CONFIG.get(domain_id)

def get_all_pro_domains() -> List[str]:
    """Retrieve all available pro domain IDs."""
    return list(PRO_DOMAIN_CONFIG.keys())

def get_domain_data_requirements(domain_id: str) -> dict:
    """Combine structural and market data requirements for a domain."""
    config = PRO_DOMAIN_CONFIG.get(domain_id)
    if not config:
        return {}
    return {
        "structural": config.get("structural_data", {}),
        "market": config.get("market_data", {})
    }

def infer_domain_from_topic(topic: str) -> str:
    """Map a topic (e.g. from an alert) to a Pro domain ID."""
    # For now, we assume a 1:1 mapping between topic names and domain IDs
    if topic in PRO_DOMAIN_CONFIG:
        return topic
    # Add manual mappings if needed
    mapping = {
        "energy": "energy_resource_risk",
        "market": "global_market_intelligence",
        "semi": "ai_semiconductor_intelligence",
        "defense": "defense_technology",
        "supply": "supply_chain_intelligence",
        "crypto": "crypto_geopolitics"
    }
    return mapping.get(topic, "global_market_intelligence")

def get_market_symbols_for_domain(domain_id: str) -> list:
    """Retrieve all Alpha Vantage symbols associated with a domain."""
    config = PRO_DOMAIN_CONFIG.get(domain_id)
    if not config:
        return []
    return config.get("market_data", {}).get("alpha_vantage_symbols", [])

def get_structural_series_for_domain(domain_id: str) -> dict:
    """Retrieve all structural data series associated with a domain."""
    config = PRO_DOMAIN_CONFIG.get(domain_id)
    if not config:
        return {}
    return config.get("structural_data", {})
# --- Design Notes ---
# 1. Dual-use Signals: Some signals (e.g., Deep Sea Mining / Surveillance) may span multiple domains.
#    Current logic favors the primary topic, but future versions may aggregate context from multiple domains
#    (e.g., Energy + Defense + Supply Chain) for a richer analytical perspective.
