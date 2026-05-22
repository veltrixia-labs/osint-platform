"""
Central policy for Pro V2 real-time generation.

When PRO_FORCE_REALTIME_REBUILD is True (default), generation always INSERTs a fresh
report row with a new UTC timestamp — no duplicate skip, no per-domain daily cap.
"""

from __future__ import annotations

import os

# Code-level defaults: always-on real-time pipeline
PRO_FORCE_REALTIME_REBUILD = True
PRO_DISABLE_GENERATION_CAPS = True
ALERT_CLUSTER_WINDOW_HOURS = 24


def pro_compile_dedup_enabled() -> bool:
    return os.getenv("PRO_COMPILE_DEDUP", "true").lower() in ("true", "1", "yes")


def pro_disable_duplicate_guards() -> bool:
    """When compile dedup is on, skip duplicate INSERTs unless explicitly overridden."""
    if pro_compile_dedup_enabled():
        return os.getenv("PRO_DISABLE_DUPLICATE_GUARDS", "false").lower() in ("true", "1", "yes")
    return os.getenv("PRO_DISABLE_DUPLICATE_GUARDS", "true").lower() in ("true", "1", "yes")


# Back-compat for imports expecting a module-level bool
PRO_DISABLE_DUPLICATE_GUARDS = pro_disable_duplicate_guards()


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
