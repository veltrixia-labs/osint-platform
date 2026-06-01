"""
Sovereign Geo-Engine — offline GeoLocator.

Resolves a free-form location name into ``{name, lat, lon, country,
confidence}`` using the SQLite FTS5 database built by
``jobs/build_geo_db.py``.

  • Zero network calls, zero API keys.
  • Sub-millisecond lookups via FTS5 prefix matching + indexed unindexed
    columns for ``latitude / longitude / country_code / population``.
  • Population-DESC sort ensures Paris-FR beats Paris-TX and the curated
    geopolitical chokepoints (synthetic population) beat any coincidentally-
    named city.

Usage:
    from analysis.pro_geo_locator import GeoLocator
    geo = GeoLocator()
    print(geo.get_coordinates("Hormuz Strait"))
    # → {'name': 'Hormuz Strait', 'lat': 26.5667, 'lon': 56.25, ...}
"""
from __future__ import annotations

import logging
import re
import sqlite3
from pathlib import Path
from typing import Any, Dict, Optional, Union

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH: Path = Path(__file__).resolve().parent.parent / "data" / "geo_master.db"

# Tokens shorter than this are too noisy for prefix matching.
_MIN_TOKEN_LEN = 2

# Population thresholds for the confidence label (geonameid < 0 ⇒ chokepoint,
# always "high"). These keep `confidence` interpretable as "would I cite
# this in a brief without further verification?".
_POP_HIGH = 1_000_000
_POP_MED = 100_000


def _sanitise_match(query: str) -> str:
    """
    Turn user input into an FTS5 query string. We strip every character that
    is significant to the FTS5 query language (``*``, ``"``, ``:``, ``(``,
    ``)``, ``NEAR``, ``AND``, ``OR``, ``NOT``) and rebuild as a sequence of
    quoted prefix terms — so the query is guaranteed to be syntactically
    valid no matter how chaotic the input.
    """
    # Keep word characters, spaces, and hyphens (intra-word hyphens are part
    # of place names like "Bab-el-Mandeb"). Anything else becomes a space.
    cleaned = re.sub(r"[^\w\s\-]+", " ", query, flags=re.UNICODE)
    tokens = [t for t in cleaned.split() if len(t) >= _MIN_TOKEN_LEN]
    if not tokens:
        return ""
    # Each token wrapped in quotes (handles intra-word hyphens / digits)
    # and suffixed with `*` for prefix matching.
    return " ".join(f'"{t}"*' for t in tokens)


def _confidence_label(population: int, geonameid: int, exact_match: bool) -> str:
    """Map population + match strength to a high/medium/low label."""
    if geonameid < 0:
        # Curated chokepoint — these are authoritative by construction.
        return "high"
    if exact_match and population >= _POP_MED:
        return "high"
    if population >= _POP_HIGH:
        return "high"
    if population >= _POP_MED:
        return "medium"
    return "low"


class GeoLocator:
    """
    Read-only query interface over the Sovereign Geo-Engine SQLite DB.

    Cheap to construct — one open connection per instance. The class
    supports the context-manager protocol so callers can use::

        with GeoLocator() as geo:
            geo.get_coordinates("Tokyo")
    """

    def __init__(self, db_path: Optional[Union[Path, str]] = None) -> None:
        self.db_path = Path(db_path) if db_path else DEFAULT_DB_PATH
        if not self.db_path.exists():
            raise FileNotFoundError(
                f"Geo DB not found at {self.db_path}. "
                "Build it first: `python jobs/build_geo_db.py`"
            )
        self._conn = sqlite3.connect(
            str(self.db_path),
            check_same_thread=False,  # safe: read-only API
        )
        self._conn.row_factory = sqlite3.Row

    # Context-manager sugar
    def __enter__(self) -> "GeoLocator":
        return self

    def __exit__(self, *_exc: Any) -> None:
        self.close()

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass

    # ─── Core lookup ─────────────────────────────────────────────────────

    def get_coordinates(self, location_name: str) -> Optional[Dict[str, Any]]:
        """
        Resolve a free-form location string to its coordinates.

        Returns:
            {
              "name":         str   — canonical Unicode display name,
              "ascii_name":   str   — ASCII-folded alias,
              "lat":          float — WGS84 latitude (decimal degrees),
              "lon":          float — WGS84 longitude (decimal degrees),
              "country":      str   — ISO 3166-1 alpha-2 country code,
              "population":   int,
              "geonameid":    int   — negative for curated chokepoints,
              "confidence":   "high" | "medium" | "low",
            }
            or ``None`` when no match is found.

        Resolution strategy:
          1. Sanitise the input → quoted FTS5 prefix tokens.
          2. ``MATCH`` against ``places`` (FTS5 virtual table).
          3. ``ORDER BY CAST(population AS INTEGER) DESC`` — Tokyo beats
             Tokyo (Texas), Strait of Hormuz beats any city named Hormuz.
          4. Take the top row, derive a confidence label.
        """
        if not isinstance(location_name, str):
            return None
        query = location_name.strip()
        if not query:
            return None

        match_expr = _sanitise_match(query)
        if not match_expr:
            return None

        try:
            cur = self._conn.execute(
                """
                SELECT name, ascii_name, geonameid, latitude, longitude,
                       country_code, population
                FROM places
                WHERE places MATCH ?
                ORDER BY CAST(population AS INTEGER) DESC
                LIMIT 5
                """,
                (match_expr,),
            )
            rows = cur.fetchall()
        except sqlite3.Error as exc:
            logger.warning("GeoLocator FTS5 query failed for %r: %s", query, exc)
            return None

        if not rows:
            return None

        top = rows[0]
        try:
            population = int(top["population"])
        except (TypeError, ValueError):
            population = 0
        try:
            geonameid = int(top["geonameid"])
        except (TypeError, ValueError):
            geonameid = 0

        name = str(top["name"] or "")
        ascii_name = str(top["ascii_name"] or "")
        norm_query = query.casefold().strip()
        exact_match = (
            norm_query == name.casefold().strip()
            or norm_query == ascii_name.casefold().strip()
        )

        return {
            "name": name,
            "ascii_name": ascii_name,
            "lat": float(top["latitude"]),
            "lon": float(top["longitude"]),
            "country": str(top["country_code"] or ""),
            "population": population,
            "geonameid": geonameid,
            "confidence": _confidence_label(population, geonameid, exact_match),
        }

    def get_candidates(self, location_name: str, limit: int = 5) -> list[Dict[str, Any]]:
        """
        Like ``get_coordinates`` but returns up to ``limit`` ranked matches
        (still population-DESC). Useful when the caller wants to disambiguate
        a name interactively.
        """
        if not isinstance(location_name, str) or not location_name.strip():
            return []
        match_expr = _sanitise_match(location_name)
        if not match_expr:
            return []
        capped = max(1, min(limit, 50))
        try:
            cur = self._conn.execute(
                """
                SELECT name, ascii_name, geonameid, latitude, longitude,
                       country_code, population
                FROM places
                WHERE places MATCH ?
                ORDER BY CAST(population AS INTEGER) DESC
                LIMIT ?
                """,
                (match_expr, capped),
            )
            rows = cur.fetchall()
        except sqlite3.Error as exc:
            logger.warning("GeoLocator candidate query failed for %r: %s", location_name, exc)
            return []
        out: list[Dict[str, Any]] = []
        norm = location_name.strip().casefold()
        for r in rows:
            try:
                pop = int(r["population"])
            except (TypeError, ValueError):
                pop = 0
            try:
                gid = int(r["geonameid"])
            except (TypeError, ValueError):
                gid = 0
            exact = norm in (str(r["name"]).casefold(), str(r["ascii_name"]).casefold())
            out.append({
                "name": r["name"],
                "ascii_name": r["ascii_name"],
                "lat": float(r["latitude"]),
                "lon": float(r["longitude"]),
                "country": r["country_code"],
                "population": pop,
                "geonameid": gid,
                "confidence": _confidence_label(pop, gid, exact),
            })
        return out
