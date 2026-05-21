"""
Central policy for Pro V2 real-time generation.

When PRO_FORCE_REALTIME_REBUILD is True (default), generation always INSERTs a fresh
report row with a new UTC timestamp — no duplicate skip, no per-domain daily cap.
"""

from __future__ import annotations

import os

# Code-level defaults: always-on real-time pipeline (env cannot disable force INSERT)
PRO_FORCE_REALTIME_REBUILD = True
PRO_DISABLE_DUPLICATE_GUARDS = True
PRO_DISABLE_GENERATION_CAPS = True
ALERT_CLUSTER_WINDOW_HOURS = 24


def pro_automation_enabled() -> bool:
    if PRO_FORCE_REALTIME_REBUILD:
        return True
    return os.getenv("ENABLE_PRO_AUTOMATION", "false").lower() == "true"


def pro_automation_dry_run() -> bool:
    if PRO_FORCE_REALTIME_REBUILD:
        return False
    return os.getenv("PRO_AUTOMATION_DRY_RUN", "true").lower() == "true"


def pro_regen_after_external_sync() -> bool:
    if PRO_FORCE_REALTIME_REBUILD:
        return True
    return os.getenv("PRO_REGEN_AFTER_SYNC", "true").lower() in ("true", "1", "yes")
