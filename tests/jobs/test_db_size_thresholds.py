"""DB size alarm thresholds (config/settings.py; vault audit §12.87(e)): 525 / 670 MiB of pg_database_size."""
import pytest

import jobs.cleanup_job as cj
from config.settings import Settings


def test_defaults_are_525_and_670(monkeypatch):
    monkeypatch.delenv("DB_SIZE_WARNING_MB", raising=False)
    monkeypatch.delenv("DB_SIZE_CRITICAL_MB", raising=False)
    import importlib
    import config.settings as cs
    fresh = importlib.reload(cs).Settings()
    assert (fresh.db_size_warning_mb, fresh.db_size_critical_mb) == (525, 670)
    importlib.reload(cs)  # restore the module's original state for other tests


@pytest.mark.parametrize("size_mib,expected", [
    (398.4, None),          # today's size (§12.86(d)): no alarm. Under the old 400 it was 1.6 MiB from firing.
    (524.99, None),
    (525.0, "warning"),
    (669.99, "warning"),
    (670.0, "critical"),
])
async def test_run_db_size_check_levels(monkeypatch, size_mib, expected):
    sent = []

    async def _size(db):
        return size_mib

    async def _metric(db, key, value):
        return None

    async def _notify(message, level="warning"):
        sent.append(level)

    monkeypatch.setattr(cj, "get_db_size_mb", _size)
    monkeypatch.setattr(cj, "update_system_metric", _metric)
    monkeypatch.setattr(cj, "send_webhook_notification", _notify)
    emergency = []

    async def _cleanup(db, dry_run=None):
        emergency.append(dry_run)

    # At the critical level run_db_size_check also deletes data (EMERGENCY cleanup, dry_run=False).
    monkeypatch.setattr(cj, "run_alert_cleanup", _cleanup)
    monkeypatch.setattr(cj, "run_retention_cleanup", _cleanup)
    monkeypatch.setattr(cj.settings, "db_size_warning_mb", 525)
    monkeypatch.setattr(cj.settings, "db_size_critical_mb", 670)
    await cj.run_db_size_check(object())
    assert sent == ([] if expected is None else [expected])
    assert emergency == ([False, False] if expected == "critical" else [])
