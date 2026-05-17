import re
from collections import defaultdict

_MIN_TICKER_LEN = 4
_MIN_TOTAL_SCORE = 2.0
_MIN_NAME_TOKEN_LEN = 3

_NAME_TOKEN_STOPWORDS = frozenset({
    "the", "and", "for", "inc", "ltd", "corp", "co", "company", "group", "holdings",
    "international", "global", "national",
})


def _name_first_token(name: str) -> str:
    """Leading significant token for partial name match (e.g. NVIDIA from NVIDIA Corporation)."""
    cleaned = re.sub(r"[^\w\s]", " ", (name or "").lower())
    for token in cleaned.split():
        if len(token) >= _MIN_NAME_TOKEN_LEN and token not in _NAME_TOKEN_STOPWORDS:
            return token
    return ""


def _word_in_text(word: str, haystack: str) -> bool:
    if not word or not haystack:
        return False
    return bool(re.search(rf"\b{re.escape(word)}\b", haystack, flags=re.IGNORECASE))


def match_news_to_companies(items, rankings, stakeholders) -> tuple[list[dict], list[dict]]:
    """
    Rule-based matcher: cross-references OSINT items against registered
    Stakeholders to identify potentially affected companies.

    A company is included ONLY if at least one "strong match" exists:
      - Company name found in item title
      - Company name found in item summary
      - Ticker match (>= 4 chars, word-boundary)
      - First name token in title/summary (e.g. NVIDIA in "NVIDIA Corporation")
      - Dependency target match

    Weak signals (sector/category, description keywords, dependency type)
    are disabled or act as supplementary bonuses only.
    """
    company_impacts_map: dict[str, dict] = {}

    ranking_by_item_id = {str(r.item_id): r for r in rankings or []}

    for stakeholder in stakeholders:
        sh_name = stakeholder.get("name", "")
        sh_ticker = stakeholder.get("ticker", "") or ""
        sh_sector = stakeholder.get("sector") or "Unknown"
        sh_country = stakeholder.get("country") or "Unknown"
        top_deps = stakeholder.get("top_dependencies", [])

        name_lower = sh_name.lower()
        name_token = _name_first_token(sh_name)
        ticker_upper = sh_ticker.strip().upper()
        sector_lower = sh_sector.lower()

        ticker_eligible = len(ticker_upper) >= _MIN_TICKER_LEN

        total_score = 0.0
        match_basis_set: set[str] = set()
        related_news: list[dict] = []
        strong_match_count = 0

        for item in items:
            title_raw = getattr(item, "title", "") or ""
            summary_raw = getattr(item, "summary", "") or ""
            title = title_raw.lower()
            summary = summary_raw.lower()
            text = title + " " + summary
            category = (
                getattr(item, "category", "") or getattr(item, "rough_category", "") or ""
            ).lower()

            item_score = 0.0
            item_matches: list[str] = []
            strong_match_found = False

            # ── 1. Company Name in Title: +5.0 ──
            if name_lower and name_lower in title:
                item_score += 5.0
                item_matches.append("Company Name in Title")
                strong_match_found = True

            # ── 2. Company Name in Summary: +3.0 ──
            elif name_lower and name_lower in summary:
                item_score += 3.0
                item_matches.append("Company Name in Summary")
                strong_match_found = True

            # ── 3. First name token (e.g. NVIDIA): +4.0 title / +2.5 summary ──
            elif name_token and _word_in_text(name_token, title):
                item_score += 4.0
                item_matches.append(f"Name Token in Title ({name_token})")
                strong_match_found = True
            elif name_token and _word_in_text(name_token, summary):
                item_score += 2.5
                item_matches.append(f"Name Token in Summary ({name_token})")
                strong_match_found = True

            # ── 4. Ticker match (>= 4 chars, word-boundary): +3.5 ──
            elif ticker_eligible and _word_in_text(ticker_upper, text):
                item_score += 3.5
                item_matches.append(f"Ticker Match ({ticker_upper})")
                strong_match_found = True

            # ── 5. Dependency Target Match: weight × 3.0 ──
            for dep in top_deps:
                target = (dep.get("target") or "").lower()
                weight = float(dep.get("weight", 0.5))

                if target and len(target) > 3 and target in text:
                    item_score += 3.0 * weight
                    item_matches.append(f"Dependency Match: {dep.get('target')}")
                    strong_match_found = True

                # dependency type matching: DISABLED for Free tier
                # (too many false positives from generic types like 'policy', 'supply')

            # ── 6. Sector/Category bonus (supplementary only) ──
            if strong_match_found and sector_lower and sector_lower in category:
                item_score += 0.5

            # description keyword matching: DISABLED for Free tier
            # (generic words cause excessive noise; re-enable after NER integration)

            # ── 7. SignalRanking.score bonus (strong match only) ──
            if strong_match_found and item_score > 0:
                ranking = ranking_by_item_id.get(str(item.id))
                r_score = (
                    ranking.score
                    if ranking and getattr(ranking, "score", None) is not None
                    else getattr(item, "lightweight_score", None) or 0.0
                )
                item_score += float(r_score) * 0.5

            # ── Accumulate ──
            if item_score > 0 and strong_match_found:
                strong_match_count += 1
                total_score += item_score
                for mb in item_matches:
                    match_basis_set.add(mb)

                pub_date = getattr(item, "published_at", None) or getattr(item, "created_at", None)
                pub_str = (
                    pub_date.strftime("%Y-%m-%d %H:%M")
                    if hasattr(pub_date, "strftime")
                    else str(pub_date) if pub_date else "Unknown"
                )

                related_news.append({
                    "title": getattr(item, "title", ""),
                    "source": (
                        getattr(item, "source_name", None)
                        or getattr(item, "source_group", None)
                        or "Unknown"
                    ),
                    "published": pub_str,
                    "item_score": item_score,
                })

        # ── Gate: strong match required & match_basis must be non-empty ──
        if strong_match_count == 0:
            continue
        if not match_basis_set:
            continue
        if total_score < _MIN_TOTAL_SCORE:
            continue

        # Impact Level logic is removed for Free tier
        related_news.sort(key=lambda x: x["item_score"], reverse=True)

        company_impacts_map[sh_name] = {
            "company_name": sh_name,
            "ticker": sh_ticker if sh_ticker else None,
            "sector": sh_sector,
            "country": sh_country,
            "match_basis": list(match_basis_set)[:3],
            "related_news_count": len(related_news),
            "top_related_news": related_news[:3],
            "_internal_score": float(total_score)
        }

    # Sort by score descending
    company_impacts = sorted(
        company_impacts_map.values(), key=lambda x: x["_internal_score"], reverse=True
    )

    # ── Aggregate Sector Impacts ──
    sector_map: dict[str, dict] = defaultdict(
        lambda: {
            "matched_entities": 0,
            "related_news_count": 0,
            "total_score": 0.0
        }
    )
    for ci in company_impacts:
        s = ci["sector"]
        sector_map[s]["matched_entities"] += 1
        sector_map[s]["related_news_count"] += ci["related_news_count"]
        sector_map[s]["total_score"] += ci["_internal_score"]

    sector_impacts = []
    for s, stats in sector_map.items():
        if stats["matched_entities"] == 0:
            continue

        sector_impacts.append({
            "sector": s,
            "matched_entities": stats["matched_entities"],
            "related_news_count": stats["related_news_count"]
        })

    # Sort by matched_entities
    def _sector_sort_key(si):
        return (-si["matched_entities"], -si["related_news_count"])

    sector_impacts.sort(key=_sector_sort_key)

    return company_impacts, sector_impacts


def sector_impacts_from_companies(company_impacts: list[dict]) -> list[dict]:
    """Re-aggregate sector stats from a (possibly merged) company_impacts list."""
    sector_map: dict[str, dict] = defaultdict(
        lambda: {
            "matched_entities": 0,
            "related_news_count": 0,
            "total_score": 0.0,
        }
    )
    for ci in company_impacts or []:
        s = ci.get("sector") or "Unknown"
        sector_map[s]["matched_entities"] += 1
        sector_map[s]["related_news_count"] += int(ci.get("related_news_count") or 0)
        sector_map[s]["total_score"] += float(ci.get("_internal_score") or 0.0)

    sector_impacts: list[dict] = []
    for s, stats in sector_map.items():
        if stats["matched_entities"] == 0:
            continue
        sector_impacts.append(
            {
                "sector": s,
                "matched_entities": stats["matched_entities"],
                "related_news_count": stats["related_news_count"],
            }
        )

    def _sector_sort_key(si: dict) -> tuple:
        return (-si["matched_entities"], -si["related_news_count"])

    sector_impacts.sort(key=_sector_sort_key)
    return sector_impacts
