"""
Sovereign Geo-Engine — offline GeoNames FTS5 builder.

Downloads cities1000.zip from GeoNames, extracts it, then bulk-loads the
~150k record corpus into a SQLite database with an FTS5 virtual table for
blazing-fast name search. Also injects a curated list of geopolitical
choke-points so the GeoLocator can resolve maritime / strategic features
that are NOT present in the cities corpus.

Zero network calls and zero API keys at query time — all resolution is
purely local against the resulting `data/geo_master.db`.

Run:
    python jobs/build_geo_db.py            # uses cached zip if present
    python jobs/build_geo_db.py --force    # re-download
"""
from __future__ import annotations

import argparse
import logging
import sqlite3
import sys
import time
import zipfile
from pathlib import Path
from typing import Iterator, List, Tuple

import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("build_geo_db")

GEONAMES_URL = "http://download.geonames.org/export/dump/cities1000.zip"
CITIES_TXT = "cities1000.txt"
DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DB_PATH = DATA_DIR / "geo_master.db"
ZIP_PATH = DATA_DIR / "cities1000.zip"

# Synthetic chokepoint records. Negative geonameids never collide with the
# real GeoNames namespace; the inflated population makes them bubble to the
# top of any name-collision sort (e.g. someone typing "Hormuz" gets the
# strait, not a coincidentally-named city).
CHOKEPOINT_POPULATION = 999_999_999
GEOPOLITICAL_CHOKEPOINTS: List[dict] = [
    {"geonameid": -1, "name": "Strait of Hormuz",   "ascii_name": "Strait of Hormuz",   "latitude": 26.5667, "longitude":  56.2500, "country_code": "IR"},
    {"geonameid": -2, "name": "Suez Canal",          "ascii_name": "Suez Canal",         "latitude": 30.7050, "longitude":  32.3481, "country_code": "EG"},
    {"geonameid": -3, "name": "Panama Canal",        "ascii_name": "Panama Canal",       "latitude":  9.0800, "longitude": -79.6800, "country_code": "PA"},
    {"geonameid": -4, "name": "Strait of Malacca",   "ascii_name": "Strait of Malacca",  "latitude":  4.0000, "longitude": 100.0000, "country_code": "MY"},
    {"geonameid": -5, "name": "Taiwan Strait",       "ascii_name": "Taiwan Strait",      "latitude": 24.8000, "longitude": 119.9000, "country_code": "TW"},
    # Common synonyms / alternates so reversed-word queries resolve cleanly.
    {"geonameid": -6, "name": "Hormuz Strait",       "ascii_name": "Hormuz Strait",      "latitude": 26.5667, "longitude":  56.2500, "country_code": "IR"},
    {"geonameid": -7, "name": "Bab-el-Mandeb",       "ascii_name": "Bab-el-Mandeb",      "latitude": 12.5833, "longitude":  43.3333, "country_code": "YE"},
    {"geonameid": -8, "name": "Bosphorus Strait",    "ascii_name": "Bosphorus Strait",   "latitude": 41.1191, "longitude":  29.0700, "country_code": "TR"},
]

# cities1000.txt is tab-separated, no header. Field positions:
#   0  geonameid           7  feature code
#   1  name                8  country code   ← we use
#   2  asciiname           9  cc2
#   3  alternatenames     10  admin1 code
#   4  latitude       ←   11  admin2 code
#   5  longitude      ←   12  admin3 code
#   6  feature class      13  admin4 code
#                         14  population     ← we use


def download_cities_zip(target: Path) -> None:
    """Stream the GeoNames archive to disk with a coarse progress bar."""
    logger.info("Downloading %s → %s", GEONAMES_URL, target)
    started = time.time()
    target.parent.mkdir(parents=True, exist_ok=True)
    with requests.get(GEONAMES_URL, stream=True, timeout=180) as resp:
        resp.raise_for_status()
        total = int(resp.headers.get("Content-Length") or 0)
        written = 0
        chunk_size = 64 * 1024
        report_every = 4 * 1024 * 1024  # progress line every 4 MB
        next_report = report_every
        with open(target, "wb") as fh:
            for chunk in resp.iter_content(chunk_size=chunk_size):
                if not chunk:
                    continue
                fh.write(chunk)
                written += len(chunk)
                if written >= next_report:
                    pct = (written / total * 100) if total else 0.0
                    sys.stdout.write(
                        f"\r  {written/1024/1024:6.1f} MB"
                        + (f" / {total/1024/1024:6.1f} MB ({pct:5.1f}%)" if total else "")
                    )
                    sys.stdout.flush()
                    next_report += report_every
        sys.stdout.write("\n")
    logger.info(
        "Downloaded %s in %.1fs (%.1f MB)",
        target.name, time.time() - started, written / 1024 / 1024,
    )


def extract_txt(zip_path: Path, dest_dir: Path) -> Path:
    """Extract cities1000.txt next to the zip; idempotent."""
    logger.info("Extracting %s …", zip_path.name)
    with zipfile.ZipFile(zip_path) as z:
        z.extract(CITIES_TXT, dest_dir)
    txt = dest_dir / CITIES_TXT
    logger.info("Extracted %s (%.1f MB)", txt.name, txt.stat().st_size / 1024 / 1024)
    return txt


def iter_city_rows(txt_path: Path) -> Iterator[Tuple]:
    """
    Yield validated (geonameid, name, ascii_name, lat, lon, cc, population)
    tuples — drop rows that are malformed / missing critical fields.
    """
    with open(txt_path, encoding="utf-8") as fh:
        for line in fh:
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 15:
                continue
            try:
                gid = int(parts[0])
                lat = float(parts[4])
                lon = float(parts[5])
                pop = int(parts[14] or "0")
            except (ValueError, IndexError):
                continue
            name = parts[1].strip()
            ascii_name = parts[2].strip() or name
            cc = (parts[8] or "").strip()
            if not name:
                continue
            yield (gid, name, ascii_name, lat, lon, cc, pop)


def build_db(txt_path: Path, db_path: Path) -> int:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()
        logger.info("Removed existing %s for clean rebuild", db_path.name)
    logger.info("Creating SQLite database: %s", db_path)

    conn = sqlite3.connect(str(db_path))
    try:
        # Performance pragmas for bulk loads. After the build we restore safe
        # defaults so production reads aren't impacted.
        conn.execute("PRAGMA journal_mode=MEMORY")
        conn.execute("PRAGMA synchronous=OFF")
        conn.execute("PRAGMA temp_store=MEMORY")
        conn.execute("PRAGMA cache_size=-65536")  # 64MB in-memory page cache

        conn.execute(
            """
            CREATE VIRTUAL TABLE places USING fts5(
                name,
                ascii_name,
                geonameid     UNINDEXED,
                latitude      UNINDEXED,
                longitude     UNINDEXED,
                country_code  UNINDEXED,
                population    UNINDEXED,
                tokenize='unicode61 remove_diacritics 2'
            )
            """
        )

        rows_inserted = 0
        batch_size = 5000
        batch: list = []
        started = time.time()
        insert_sql = (
            "INSERT INTO places(name, ascii_name, geonameid, latitude, longitude, country_code, population) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)"
        )

        conn.execute("BEGIN")
        for gid, name, ascii_name, lat, lon, cc, pop in iter_city_rows(txt_path):
            batch.append((name, ascii_name, gid, lat, lon, cc, pop))
            if len(batch) >= batch_size:
                conn.executemany(insert_sql, batch)
                rows_inserted += len(batch)
                batch.clear()
                if rows_inserted % 25_000 == 0:
                    elapsed = time.time() - started
                    rate = rows_inserted / elapsed if elapsed > 0 else 0
                    sys.stdout.write(f"\r  inserted {rows_inserted:>7,d} rows ({rate:,.0f}/s)")
                    sys.stdout.flush()
        if batch:
            conn.executemany(insert_sql, batch)
            rows_inserted += len(batch)
        conn.execute("COMMIT")
        sys.stdout.write("\n")
        logger.info(
            "Inserted %s city rows in %.1fs",
            f"{rows_inserted:,}", time.time() - started,
        )

        # Geopolitical chokepoints
        cp_rows = [
            (c["name"], c["ascii_name"], c["geonameid"], c["latitude"],
             c["longitude"], c["country_code"], CHOKEPOINT_POPULATION)
            for c in GEOPOLITICAL_CHOKEPOINTS
        ]
        conn.executemany(insert_sql, cp_rows)
        conn.commit()
        logger.info("Inserted %d geopolitical chokepoints", len(cp_rows))

        # Optimise the FTS index for faster MATCH queries.
        conn.execute("INSERT INTO places(places) VALUES('optimize')")
        conn.commit()
        return rows_inserted + len(cp_rows)
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the Sovereign Geo-Engine SQLite DB.")
    parser.add_argument("--force", action="store_true",
                        help="Force re-download of cities1000.zip (even if cached).")
    args = parser.parse_args()

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    if args.force or not ZIP_PATH.exists():
        download_cities_zip(ZIP_PATH)
    else:
        logger.info(
            "Reusing cached %s (%.1f MB) — pass --force to re-download",
            ZIP_PATH.name, ZIP_PATH.stat().st_size / 1024 / 1024,
        )

    txt_path = extract_txt(ZIP_PATH, DATA_DIR)
    total = build_db(txt_path, DB_PATH)

    size_mb = DB_PATH.stat().st_size / 1024 / 1024
    logger.info("Sovereign Geo-Engine DB ready: %s (%s rows, %.1f MB)",
                DB_PATH, f"{total:,}", size_mb)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
