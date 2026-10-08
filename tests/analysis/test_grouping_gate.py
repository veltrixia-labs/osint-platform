"""The grouping specificity gate and best-member comparison in analysis/clustering.py.

Every title here is a real production title from the 2026-10-08 replay. Pure: no database.
"""
from analysis.clustering import (
    CATEGORY_THRESHOLD_KEYS,
    CATEGORY_THRESHOLDS,
    group_items,
    shares_specific_token,
)


class _Item:
    def __init__(self, title, category="energy_resource_risk"):
        self.title = title
        self.category = category
        self.rough_category = None


def _together(groups, a, b):
    return any(a in g and b in g for g in groups)


# ── Panama: the regression this change exists for ──────────────────────────────

PANAMA = "Panama Canal to limit shipping ahead of extreme weather during El Nino"
CHINA = "China growth straining global auto shipping capacity: Liner CEO"
SHIPPING_BAG = [
    "South Korea Tests Arctic Shipping Route to Europe",
    "Geekom admits to shipping malware-laced network drivers for AMD mini PCs — company respond",
    "The world’s third-largest shipping line has a new US chief",
    "Port of Corpus Christi Joins U.S. Push for Nuclear-Powered Shipping",
]


def test_panama_and_china_share_only_shipping_and_do_not_merge():
    # Before the gate these scored ~0.49 against a 0.40 threshold on "shipping" alone
    # (lexical token + sector entity + class keyword), and the two alerts shared all six
    # evidence articles.
    assert not shares_specific_token(PANAMA, CHINA)
    titles = [PANAMA, CHINA] + SHIPPING_BAG
    for order in (titles, titles[::-1]):
        items = [_Item(t, "supply_chain_intelligence") for t in order]
        groups = group_items(items)
        assert all(len(g) == 1 for g in groups), [[i.title for i in g] for g in groups if len(g) > 1]


# ── same-event reports the seed-only comparison split, best-member rejoins ───────

def test_iran_oil_minister_resignation_reports_rejoin():
    # Third title matches the SECOND (a non-seed member), not the first.
    seed = _Item("Iran’s Offshore Oil Stockpile Nears Exhaustion as Blockade Chokes New Supply")
    a = _Item("Iran’s Oil Minister Resigns as U.S. Blockade Chokes Crude Exports")
    b = _Item("Iran’s oil minister resigns as country’s economic crisis worsens")
    groups = group_items([seed, a, b])
    assert _together(groups, a, b)


def test_hormuz_flows_back_to_pre_war_levels_reports_rejoin():
    seed = _Item("Standard Chartered Says Hormuz Oil Flows Are Far From Normal")
    a = _Item("Oil Prices Fall as Hormuz Crude Flows Top Pre-War Levels")
    b = _Item("Crude oil exports from strait of Hormuz largely return to pre-war levels")
    groups = group_items([seed, a, b])
    assert _together(groups, a, b)


def test_exact_duplicate_titles_group():
    a = _Item("Getting Oil Through Hormuz Is a Risky Job")
    b = _Item("No Lights, No Radio: Getting Oil Through Hormuz Is a Risky Job")
    assert shares_specific_token(a.title, b.title)
    assert _together(group_items([a, b]), a, b)


# ── tokenizer artifacts are not specific words ─────────────────────────────────

def test_a_bare_number_is_not_a_specific_word():
    # "$100" tokenizes to "100"; it chained "$100 Oil" into the G7 100-million-barrel group.
    assert not shares_specific_token(
        "Why $100 Oil Is Hard to Kill",
        "IEA Discusses G7's 100 Million-Barrel Oil and Diesel Release",
    )


def test_single_letters_from_us_are_not_specific_words():
    # "U.S." tokenizes to "u" + "s"; that linked the Korea oil project to the Iran group.
    assert not shares_specific_token(
        "Iran’s Oil Minister Resigns as U.S. Blockade Chokes Crude Exports",
        "Trump Says South Korea Deal Includes $8.4 Billion U.S. Oil Project",
    )


def test_letters_with_digits_still_count():
    # "g7" is a name, not an artifact: the G7 release reports must still be able to merge.
    assert shares_specific_token(
        "Oil Falls as G7 Taps Emergency Supplies",
        "G7 to release up to 100m barrels of emergency oil and diesel reserves",
    )


# ── category threshold keys ────────────────────────────────────────────────────

def test_strategic_codes_resolve_to_a_threshold_key():
    for code, key in CATEGORY_THRESHOLD_KEYS.items():
        assert key in CATEGORY_THRESHOLDS, code
