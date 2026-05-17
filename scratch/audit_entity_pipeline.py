"""Quick audit: entity pipeline / Context Brief counts (local DB)."""
from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy import func, select

from analysis.clustering import extract_entities
from analysis.free_company_matcher import match_news_to_companies
from db.database import AsyncSessionLocal
from db.models import AlertLog, Item, Stakeholder


async def main() -> None:
    async with AsyncSessionLocal() as db:
        n_stk = (await db.execute(select(func.count()).select_from(Stakeholder))).scalar() or 0
        print(f"Stakeholders: {n_stk}")
        if n_stk:
            rows = (
                await db.execute(
                    select(Stakeholder.name, Stakeholder.ticker, Stakeholder.is_auto_provisioned).limit(8)
                )
            ).all()
            for r in rows:
                print(f"  - {r[0]!r} ticker={r[1]!r} auto={r[2]}")

        for kw in ("tesla", "nvidia"):
            c = (
                await db.execute(select(func.count()).select_from(Item).where(Item.title.ilike(f"%{kw}%")))
            ).scalar()
            print(f"Items with {kw!r} in title: {c}")

        items = (
            await db.execute(
                select(Item)
                .where(Item.title.ilike("%nvidia%") | Item.title.ilike("%tesla%"))
                .order_by(Item.created_at.desc())
                .limit(3)
            )
        ).scalars().all()
        for it in items:
            ents = extract_entities(it.title or "")
            print(f"\nTitle: {(it.title or '')[:80]}")
            print(f"  clustering.extract_entities org={list(ents['org'])[:5]} geo={list(ents['geo'])[:3]}")

        alerts = (
            await db.execute(select(AlertLog).order_by(AlertLog.triggered_at.desc()).limit(15))
        ).scalars().all()
        zero = 0
        for a in alerts:
            meta = a.metadata_json if isinstance(a.metadata_json, dict) else {}
            fa = meta.get("free_alert") if isinstance(meta, dict) else None
            ec = fa.get("related_entities_count") if isinstance(fa, dict) else None
            if ec == 0:
                zero += 1
            ci_len = len(fa.get("company_impacts") or []) if isinstance(fa, dict) else -1
            src = fa.get("related_news_source") if isinstance(fa, dict) else None
            print(
                f"alert topic={a.topic!r} entities={ec} impacts={ci_len} news_src={src}"
            )
        print(f"\n{zero}/{len(alerts)} recent alerts: related_entities_count==0")

        # Matcher dry-run on nvidia items if stakeholders exist
        if items and n_stk:
            stk_records = (await db.execute(select(Stakeholder).limit(500))).scalars().all()
            sh_list = [
                {
                    "name": s.name,
                    "ticker": s.ticker,
                    "sector": s.sector,
                    "country": s.country,
                    "top_dependencies": [],
                }
                for s in stk_records
            ]
            impacts, sectors = match_news_to_companies(items, [], sh_list)
            print(f"\nmatch_news_to_companies on {len(items)} NVDA/TSLA items -> {len(impacts)} companies")
            for c in impacts[:5]:
                print(f"  {c.get('company_name')} basis={c.get('match_basis')}")


if __name__ == "__main__":
    asyncio.run(main())
