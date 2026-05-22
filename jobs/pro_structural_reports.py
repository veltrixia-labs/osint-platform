"""
Shared identification for Pro Structural Brief rows (Pro Insight hub).
"""

from __future__ import annotations

from sqlalchemy import or_

from db.models import Report


def pro_structural_report_filters():
    """SQLAlchemy WHERE clauses matching Pro Insight list/detail rows."""
    return (
        Report.plan_required == "pro",
        Report.is_premium == True,  # noqa: E712
        or_(
            Report.report_type == "pro_structural",
            Report.title.ilike("Structural Impact Brief%"),
        ),
    )
