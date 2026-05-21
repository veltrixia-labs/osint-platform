"""
Production backfill + Pro V2 rebuild (uses DATABASE_URL from environment).

  # Sync only
  py scratch/backfill_and_rebuild_production.py --sync-only

  # Full pipeline (sync → purge → regenerate)
  py scratch/backfill_and_rebuild_production.py

  # Hit remote API instead of local DB job code
  py scratch/backfill_and_rebuild_production.py --remote \\
    --api-base https://osint-platform.onrender.com \\
    --secret YOUR_PRO_BRIEF_REGEN_SECRET
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


async def run_local(*, sync_only: bool, full: bool, purge: bool) -> dict:
    from jobs.pro_backfill_pipeline import run_backfill_and_rebuild, run_sync_external_data

    if sync_only:
        return await run_sync_external_data(full_pipeline=full, include_market=True)
    return await run_backfill_and_rebuild(purge_first=purge, full_sync=full)


def run_remote(*, api_base: str, secret: str, sync_only: bool, full: bool, purge: bool) -> dict:
    import urllib.error
    import urllib.request

    base = api_base.rstrip("/")
    if sync_only:
        path = f"/api/dev/sync-external-data?full={'true' if full else 'false'}"
    else:
        path = f"/api/dev/backfill-and-rebuild?purge={'true' if purge else 'false'}&full={'true' if full else 'false'}"

    url = f"{base}{path}"
    req = urllib.request.Request(
        url,
        method="POST",
        headers={
            "X-Pro-Regen-Secret": secret,
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=3600) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code} {url}: {detail}") from exc


async def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill external data and rebuild Pro V2 briefs")
    parser.add_argument("--sync-only", action="store_true", help="Only run external data sync")
    parser.add_argument("--full", action="store_true", help="Full daily external sync pipeline")
    parser.add_argument("--no-purge", action="store_true", help="Skip purge on rebuild")
    parser.add_argument("--remote", action="store_true", help="POST to production API")
    parser.add_argument("--api-base", default="https://osint-platform.onrender.com")
    parser.add_argument(
        "--secret",
        default=os.environ.get("PRO_BRIEF_REGEN_SECRET", "").strip(),
        help="X-Pro-Regen-Secret (or PRO_BRIEF_REGEN_SECRET env)",
    )
    args = parser.parse_args()

    if args.remote:
        if not args.secret:
            raise SystemExit("Set --secret or PRO_BRIEF_REGEN_SECRET for remote calls.")
        result = run_remote(
            api_base=args.api_base,
            secret=args.secret,
            sync_only=args.sync_only,
            full=args.full,
            purge=not args.no_purge,
        )
    else:
        result = await run_local(
            sync_only=args.sync_only,
            full=args.full,
            purge=not args.no_purge,
        )

    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    asyncio.run(main())
