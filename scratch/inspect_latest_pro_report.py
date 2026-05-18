"""
Force-generate a Pro Structural Brief from the latest AlertLog and inspect output.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from typing import Any, Optional

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.database import AsyncSessionLocal
from db.models import AlertLog
from jobs.pro_report_generator import run_pro_structural_report_generation


class AlertRepository:
    """Lightweight read helper for AlertLog (scratch / inspection use)."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_latest(self) -> Optional[AlertLog]:
        stmt = (
            select(AlertLog)
            .where(AlertLog.suppressed == False)  # noqa: E712
            .order_by(desc(AlertLog.triggered_at))
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()


def _json_default(obj: Any) -> Any:
    if hasattr(obj, "isoformat"):
        return obj.isoformat()
    return str(obj)


def _print_section_analysis(payload: dict) -> None:
    macro = payload.get("structural_context", {}).get("macro_observations", [])
    market = payload.get("market_confirmation", {})
    cov = payload.get("coverage_matrix", {})

    new_series_prefixes = (
        "0003",  # e-Stat
        "WCESTUS1",
        "WPULEUS3",
        "WCRFPUS2",
        "FM.D.U2",
        "EXR.D",
        "ICP.M",
        "BCB.",
        "OPEC.",
        "WORLD.",
        "FDI.AMS",
        "IMTS.",
    )

    print("\n" + "=" * 80)
    print("SECTION 06 - Quantitative Context (macro_observations)")
    print("=" * 80)
    print(f"Total macro series in payload: {len(macro)}")
    for obs in macro:
        sid = obs.get("series_id", "")
        tag = "NEW-GLOBAL" if any(sid.startswith(p) or p in sid for p in new_series_prefixes) else "LEGACY"
        print(
            f"  [{tag}] {sid} | source={obs.get('source')} | "
            f"value={obs.get('latest_value')} | change_pct={obs.get('change_pct')} | "
            f"date={obs.get('latest_date')}"
        )

    print("\n" + "=" * 80)
    print("SECTION 07 - Market Confirmation")
    print("=" * 80)
    print(f"Status: {market.get('status')}")
    print(f"Positive movers: {market.get('positive_movers')} | Negative: {market.get('negative_movers')}")
    for row in market.get("latest_prices", []):
        print(
            f"  {row.get('symbol')}: {row.get('percent_change')}% "
            f"(close={row.get('latest_close')}, date={row.get('latest_date')})"
        )
    print("\nBreakdown by group:")
    for g in market.get("breakdown", []):
        print(f"  {g.get('group')}: status={g.get('status')} | instruments={g.get('instruments')}")

    print("\n" + "=" * 80)
    print("SECTION 13 - Coverage Matrix")
    print("=" * 80)
    print(json.dumps(cov, indent=2, default=_json_default))


async def main() -> None:
    alert_id: Optional[str] = None
    async with AsyncSessionLocal() as session:
        repo = AlertRepository(session)
        alert = await repo.get_latest()
        if not alert:
            print("No AlertLog found in database.")
            return

        alert_id = str(alert.id)

        print("=" * 80)
        print("LATEST ALERT")
        print("=" * 80)
        print(f"  id:          {alert.id}")
        print(f"  topic:       {alert.topic}")
        print(f"  severity:    {alert.severity}")
        print(f"  target:      {alert.target_label}")
        print(f"  triggered:   {alert.triggered_at}")

        from analysis.pro_domain_config import infer_domain_from_topic

        domain_id = infer_domain_from_topic(alert.topic)
        print(f"  domain_id:   {domain_id}")

    print("\nGenerating Pro Structural Brief...")
    report = await run_pro_structural_report_generation(alert_id=alert_id)

    print("\n" + "=" * 80)
    print("GENERATED REPORT")
    print("=" * 80)
    print(f"  id:          {report.id}")
    print(f"  title:       {report.title}")
    print(f"  topic_code:  {report.topic_code}")
    print(f"  created_at:  {report.created_at}")

    payload = report.structured_payload or {}
    _print_section_analysis(payload)

    out_md = os.path.join(os.path.dirname(__file__), "inspect_latest_pro_report.md")
    out_json = os.path.join(os.path.dirname(__file__), "inspect_latest_pro_report_payload.json")
    with open(out_md, "w", encoding="utf-8") as f:
        f.write(report.content_markdown or "")
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, default=_json_default)
    print(f"\nSaved: {out_md}")
    print(f"Saved: {out_json}")

    print("\n" + "=" * 80)
    print("STRUCTURED_PAYLOAD (JSON)")
    print("=" * 80)
    print(json.dumps(payload, indent=2, default=_json_default))

    print("\n" + "=" * 80)
    print("CONTENT_MARKDOWN (FULL)")
    print("=" * 80)
    print(report.content_markdown or "")


if __name__ == "__main__":
    asyncio.run(main())
