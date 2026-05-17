import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

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


def _word_in_text_lower(word: str, haystack_lower: str) -> bool:
    if not word or not haystack_lower:
        return False
    return bool(re.search(rf"\b{re.escape(word.lower())}\b", haystack_lower))


@dataclass(frozen=True)
class _ItemMatchCtx:
    item: Any
    title: str
    summary: str
    text: str
    category: str
    score_bonus: float


@dataclass(frozen=True)
class _StakeholderMatchCtx:
    name: str
    name_lower: str
    name_token: str
    ticker: str
    ticker_upper: str
    ticker_eligible: bool
    sector: str
    sector_lower: str
    country: str
    deps: tuple[tuple[str, float, str], ...]


def _prepare_item_contexts(items, rankings) -> list[_ItemMatchCtx]:
    ranking_by_item_id = {str(r.item_id): r for r in rankings or []}
    contexts: list[_ItemMatchCtx] = []
    for item in items:
        title_raw = getattr(item, "title", "") or ""
        summary_raw = getattr(item, "summary", "") or ""
        title_lower = title_raw.lower()
        summary_lower = summary_raw.lower()
        category = (
            getattr(item, "category", "") or getattr(item, "rough_category", "") or ""
        ).lower()
        ranking = ranking_by_item_id.get(str(item.id))
        r_score = (
            ranking.score
            if ranking and getattr(ranking, "score", None) is not None
            else getattr(item, "lightweight_score", None) or 0.0
        )
        contexts.append(
            _ItemMatchCtx(
                item=item,
                title=title_lower,
                summary=summary_lower,
                text=title_lower + " " + summary_lower,
                category=category,
                score_bonus=float(r_score) * 0.5,
            )
        )
    return contexts


def _prepare_stakeholder_contexts(stakeholders) -> list[_StakeholderMatchCtx]:
    prepped: list[_StakeholderMatchCtx] = []
    for stakeholder in stakeholders:
        sh_name = stakeholder.get("name", "")
        sh_ticker = stakeholder.get("ticker", "") or ""
        ticker_upper = sh_ticker.strip().upper()
        deps: list[tuple[str, float, str]] = []
        for dep in stakeholder.get("top_dependencies", []):
            target = dep.get("target") or ""
            target_lower = target.lower()
            if target_lower and len(target_lower) > 3:
                deps.append(
                    (target_lower, float(dep.get("weight", 0.5)), dep.get("target") or target)
                )
        prepped.append(
            _StakeholderMatchCtx(
                name=sh_name,
                name_lower=sh_name.lower(),
                name_token=_name_first_token(sh_name),
                ticker=sh_ticker,
                ticker_upper=ticker_upper,
                ticker_eligible=len(ticker_upper) >= _MIN_TICKER_LEN,
                sector=stakeholder.get("sector") or "Unknown",
                sector_lower=(stakeholder.get("sector") or "Unknown").lower(),
                country=stakeholder.get("country") or "Unknown",
                deps=tuple(deps),
            )
        )
    return prepped


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
    item_ctxs = _prepare_item_contexts(items, rankings)
    stakeholder_ctxs = _prepare_stakeholder_contexts(stakeholders)

    for sh in stakeholder_ctxs:
        total_score = 0.0
        match_basis_set: set[str] = set()
        related_news: list[dict] = []
        strong_match_count = 0

        for ctx in item_ctxs:
            item_score = 0.0
            item_matches: list[str] = []
            strong_match_found = False

            if sh.name_lower and sh.name_lower in ctx.title:
                item_score += 5.0
                item_matches.append("Company Name in Title")
                strong_match_found = True
            elif sh.name_lower and sh.name_lower in ctx.summary:
                item_score += 3.0
                item_matches.append("Company Name in Summary")
                strong_match_found = True
            elif sh.name_token and _word_in_text_lower(sh.name_token, ctx.title):
                item_score += 4.0
                item_matches.append(f"Name Token in Title ({sh.name_token})")
                strong_match_found = True
            elif sh.name_token and _word_in_text_lower(sh.name_token, ctx.summary):
                item_score += 2.5
                item_matches.append(f"Name Token in Summary ({sh.name_token})")
                strong_match_found = True
            elif sh.ticker_eligible and _word_in_text_lower(sh.ticker_upper, ctx.text):
                item_score += 3.5
                item_matches.append(f"Ticker Match ({sh.ticker_upper})")
                strong_match_found = True

            for target_lower, weight, target_display in sh.deps:
                if target_lower in ctx.text:
                    item_score += 3.0 * weight
                    item_matches.append(f"Dependency Match: {target_display}")
                    strong_match_found = True

            if strong_match_found and sh.sector_lower and sh.sector_lower in ctx.category:
                item_score += 0.5

            if strong_match_found and item_score > 0:
                item_score += ctx.score_bonus

            if item_score > 0 and strong_match_found:
                strong_match_count += 1
                total_score += item_score
                for mb in item_matches:
                    match_basis_set.add(mb)

                item = ctx.item
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

        if strong_match_count == 0:
            continue
        if not match_basis_set:
            continue
        if total_score < _MIN_TOTAL_SCORE:
            continue

        related_news.sort(key=lambda x: x["item_score"], reverse=True)

        company_impacts_map[sh.name] = {
            "company_name": sh.name,
            "ticker": sh.ticker if sh.ticker else None,
            "sector": sh.sector,
            "country": sh.country,
            "match_basis": list(match_basis_set)[:3],
            "related_news_count": len(related_news),
            "top_related_news": related_news[:3],
            "_internal_score": float(total_score),
        }

    company_impacts = sorted(
        company_impacts_map.values(), key=lambda x: x["_internal_score"], reverse=True
    )

    sector_map: dict[str, dict] = defaultdict(
        lambda: {
            "matched_entities": 0,
            "related_news_count": 0,
            "total_score": 0.0,
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
            "related_news_count": stats["related_news_count"],
        })

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
