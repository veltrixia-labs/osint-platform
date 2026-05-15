"""
BEA Industry Code Classifier.

Classifies BEA GDP-by-Industry codes into a hierarchy level so that
queries can select the appropriate granularity and avoid double-counting.

Hierarchy
---------
- total      : GDP (the single national total)
- aggregate  : Cross-cutting subtotals (PVT, PSERV, FIRE, PROF, ICT, ...)
- sector     : Top-level industry groups (~NAICS 2-digit or BEA equivalent)
- subsector  : Mid-level breakdowns (~NAICS 3-digit)
- detail     : Fine-grained or BEA custom codes (4-digit+, combo codes)
- unknown    : Unrecognised code
"""

from typing import Set

# ── Explicit code sets ────────────────────────────────────────────────

TOTAL_CODES: Set[str] = {"GDP"}

AGGREGATE_CODES: Set[str] = {
    "PVT",      # Private industries
    "PSERV",    # Private services-producing
    "PGOOD",    # Private goods-producing
    "G",        # Government (all)
    "GF",       # Federal
    "GFG",      # Federal general government
    "GFGD",     # National defense
    "GFGN",     # Nondefense
    "GFE",      # Federal government enterprises
    "GSL",      # State and local
    "GSLG",     # State and local general government
    "GSLE",     # State and local government enterprises
    "33DG",     # Durable goods subtotal
    "31ND",     # Nondurable goods subtotal
    "FIRE",     # Finance, insurance, real estate (cross-cut)
    "PROF",     # Professional and business services (cross-cut)
    "HS",       # Housing (cross-cut)
    "ORE",      # Other real estate (cross-cut)
    "ICT",      # ICT-producing industries (cross-cut)
}

# Top-level sectors: 2-digit NAICS + BEA composite sector codes.
# These should sum roughly to GDP without double-counting.
SECTOR_CODES: Set[str] = {
    # Standard 2-digit NAICS
    "11",       # Agriculture, forestry, fishing, and hunting
    "21",       # Mining
    "22",       # Utilities
    "23",       # Construction
    "42",       # Wholesale trade
    "51",       # Information
    "52",       # Finance and insurance
    "53",       # Real estate and rental and leasing
    "54",       # Professional, scientific, and technical services
    "55",       # Management of companies and enterprises
    "56",       # Administrative and waste management services
    "61",       # Educational services
    "62",       # Health care and social assistance
    "71",       # Arts, entertainment, and recreation
    "72",       # Accommodation and food services
    "81",       # Other services, except government
    # BEA composite sector codes (equivalent to 2-digit level)
    "31G",      # Manufacturing (covers NAICS 31-33)
    "44RT",     # Retail trade (covers NAICS 44-45)
    "48TW",     # Transportation and warehousing (covers NAICS 48-49)
    # BEA super-sector codes that act as sector-level in the hierarchy
    "6",        # Educational services, health care, and social assistance
    "7",        # Arts, entertainment, recreation, accommodation, food services
}

# 3-digit NAICS subsectors (explicitly listed for clarity)
SUBSECTOR_CODES: Set[str] = {
    "111CA", "113FF",                           # Agriculture subs
    "211", "212", "213",                        # Mining subs
    "311FT", "313TT", "315AL",                  # Nondurable mfg subs
    "321", "322", "323", "324", "325", "326",   # More mfg subs
    "327", "331", "332", "333", "334", "335",   # More mfg subs
    "337", "339",                               # More mfg subs
    "441", "445", "452", "4A0",                 # Retail trade subs
    "481", "482", "483", "484", "485", "486",   # Transportation subs
    "487OS", "493",                             # Transportation subs
    "511", "512", "513", "514",                 # Information subs
    "521CI", "523", "524", "525",               # Finance subs
    "531", "532RL",                             # Real estate subs
    "561", "562",                               # Admin/waste subs
    "621", "622", "623", "624",                 # Health care subs
    "711AS", "713",                             # Arts/entertainment subs
    "721", "722",                               # Accommodation subs
}

# Detail codes: 4-digit+ NAICS or BEA custom fine-grained codes
DETAIL_CODES: Set[str] = {
    "3361MV",   # Motor vehicles, bodies and trailers, and parts
    "3364OT",   # Other transportation equipment
    "5411",     # Legal services
    "5412OP",   # Misc professional/scientific/technical services
    "5415",     # Computer systems design and related services
}


def classify_industry_code(code: str) -> str:
    """
    Classify a BEA industry code into its hierarchy level.

    Parameters
    ----------
    code : str
        A BEA industry code (e.g. "GDP", "53", "531", "5412OP").

    Returns
    -------
    str
        One of: "total", "aggregate", "sector", "subsector", "detail", "unknown"
    """
    if code in TOTAL_CODES:
        return "total"
    if code in AGGREGATE_CODES:
        return "aggregate"
    if code in SECTOR_CODES:
        return "sector"
    if code in SUBSECTOR_CODES:
        return "subsector"
    if code in DETAIL_CODES:
        return "detail"
    return "unknown"


def get_codes_by_level(level: str) -> Set[str]:
    """Return all known codes for a given hierarchy level."""
    mapping = {
        "total": TOTAL_CODES,
        "aggregate": AGGREGATE_CODES,
        "sector": SECTOR_CODES,
        "subsector": SUBSECTOR_CODES,
        "detail": DETAIL_CODES,
    }
    return mapping.get(level, set())
