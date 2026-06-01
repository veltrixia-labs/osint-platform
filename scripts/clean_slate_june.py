"""
Clean-slate June 1st purge — backup-then-purge of pre-content-first runtime noise.

Two explicit phases (run backup first; purge REFUSES to run unless a backup file
exists whose per-table line counts match the live DB delete set):

  py -3 -m scripts.clean_slate_june backup
  py -3 -m scripts.clean_slate_june purge --backup-file ./backups/pre_june1_purge_<ts>.jsonl

Cutoff = 2026-06-01T00:00:00+00:00 (UTC). Deletes rows STRICTLY BEFORE the cutoff:
  - raw_items.created_at  < cutoff
  - alert_logs.triggered_at < cutoff   (+ their alert_deliveries FK children)
KEEPS: on/after-June-1 rows and the monthly_trend_reports archive (untouched).

Backup is a single JSONL where each line is {"_table": <name>, "row": <row_to_json>}.
Non-destructive in `backup`; `purge` mutates the live production DB.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy import text
from db.database import AsyncSessionLocal

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("clean_slate_june")

CUTOFF = datetime(2026, 6, 1, 0, 0, 0, tzinfo=timezone.utc)
BACKUP_DIR = os.path.join(os.path.dirname(__file__), "..", "backups")

# (table, json-row source SQL, timestamp column for the cutoff filter)
DUMP_SPECS = [
    ("alert_logs", "alert_logs", "triggered_at"),
    (
        "alert_deliveries",
        "alert_deliveries d WHERE d.alert_log_id IN "
        "(SELECT id FROM alert_logs WHERE triggered_at < :c)",
        None,  # selected via subquery, not its own timestamp
    ),
    ("raw_items", "raw_items", "created_at"),
]


async def _expected_counts(s) -> dict[str, int]:
    counts: dict[str, int] = {}
    counts["alert_logs"] = (await s.execute(
        text("SELECT count(*) FROM alert_logs WHERE triggered_at < :c"), {"c": CUTOFF})).scalar()
    counts["alert_deliveries"] = (await s.execute(
        text("SELECT count(*) FROM alert_deliveries WHERE alert_log_id IN "
             "(SELECT id FROM alert_logs WHERE triggered_at < :c)"), {"c": CUTOFF})).scalar()
    counts["raw_items"] = (await s.execute(
        text("SELECT count(*) FROM raw_items WHERE created_at < :c"), {"c": CUTOFF})).scalar()
    return counts


async def do_backup() -> None:
    os.makedirs(BACKUP_DIR, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = os.path.join(BACKUP_DIR, f"pre_june1_purge_{ts}.jsonl")

    async with AsyncSessionLocal() as s:
        expected = await _expected_counts(s)
        logger.info("Expected delete set: %s", expected)
        written: dict[str, int] = {t: 0 for t in expected}

        with open(path, "w", encoding="utf-8") as fh:
            # alert_logs
            res = await s.stream(text(
                "SELECT row_to_json(t) FROM alert_logs t WHERE t.triggered_at < :c"), {"c": CUTOFF})
            async for row in res:
                fh.write(json.dumps({"_table": "alert_logs", "row": row[0]}, default=str) + "\n")
                written["alert_logs"] += 1
            # alert_deliveries (FK children of the deleted alert_logs)
            res = await s.stream(text(
                "SELECT row_to_json(t) FROM alert_deliveries t WHERE t.alert_log_id IN "
                "(SELECT id FROM alert_logs WHERE triggered_at < :c)"), {"c": CUTOFF})
            async for row in res:
                fh.write(json.dumps({"_table": "alert_deliveries", "row": row[0]}, default=str) + "\n")
                written["alert_deliveries"] += 1
            # raw_items
            res = await s.stream(text(
                "SELECT row_to_json(t) FROM raw_items t WHERE t.created_at < :c"), {"c": CUTOFF})
            async for row in res:
                fh.write(json.dumps({"_table": "raw_items", "row": row[0]}, default=str) + "\n")
                written["raw_items"] += 1

    logger.info("Backup written: %s", os.path.abspath(path))
    logger.info("Rows written: %s", written)
    ok = written == expected
    logger.info("VERIFY backup == expected delete set: %s", "OK" if ok else "MISMATCH")
    if not ok:
        raise SystemExit("Backup row counts do not match expected delete set; aborting.")
    print(f"BACKUP_FILE={os.path.abspath(path)}")


def _count_backup_lines(path: str) -> dict[str, int]:
    counts: dict[str, int] = {"alert_logs": 0, "alert_deliveries": 0, "raw_items": 0}
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            # cheap discriminator parse (avoids json.loads on 100k+ lines)
            if line.startswith('{"_table": "raw_items"'):
                counts["raw_items"] += 1
            elif line.startswith('{"_table": "alert_logs"'):
                counts["alert_logs"] += 1
            elif line.startswith('{"_table": "alert_deliveries"'):
                counts["alert_deliveries"] += 1
    return counts


async def do_purge(backup_file: str) -> None:
    if not backup_file or not os.path.isfile(backup_file):
        raise SystemExit(f"Backup file not found: {backup_file!r} — run `backup` first.")

    async with AsyncSessionLocal() as s:
        expected = await _expected_counts(s)
        file_counts = _count_backup_lines(backup_file)
        logger.info("DB expected delete set : %s", expected)
        logger.info("Backup file line counts: %s", file_counts)
        if file_counts != expected:
            raise SystemExit("Backup file does not match current DB delete set; aborting purge.")

        # Cascade-safe order: FK children first, then parents, then raw_items.
        d_del = (await s.execute(text(
            "DELETE FROM alert_deliveries WHERE alert_log_id IN "
            "(SELECT id FROM alert_logs WHERE triggered_at < :c)"), {"c": CUTOFF})).rowcount
        a_del = (await s.execute(text(
            "DELETE FROM alert_logs WHERE triggered_at < :c"), {"c": CUTOFF})).rowcount
        r_del = (await s.execute(text(
            "DELETE FROM raw_items WHERE created_at < :c"), {"c": CUTOFF})).rowcount
        await s.commit()

        logger.info("DELETED alert_deliveries=%d alert_logs=%d raw_items=%d", d_del, a_del, r_del)

        # Post-purge survivors
        al = (await s.execute(text("SELECT count(*) FROM alert_logs"))).scalar()
        ri = (await s.execute(text("SELECT count(*) FROM raw_items"))).scalar()
        mt = (await s.execute(text("SELECT count(*) FROM monthly_trend_reports"))).scalar()
        logger.info("SURVIVORS alert_logs=%d raw_items=%d monthly_trend_reports=%d", al, ri, mt)


async def main() -> None:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="phase", required=True)
    sub.add_parser("backup")
    pp = sub.add_parser("purge")
    pp.add_argument("--backup-file", required=True)
    args = p.parse_args()

    if args.phase == "backup":
        await do_backup()
    elif args.phase == "purge":
        await do_purge(args.backup_file)


if __name__ == "__main__":
    asyncio.run(main())
