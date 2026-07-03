"""
Memory probe helpers for the scheduler's ``[MEM]`` log lines.

Two distinct numbers, deliberately kept separate:

* ``current_rss_mb()`` — the RESIDENT set the process holds *right now*. This is
  the value that DROPS after ``session.expire_all()`` / ``gc.collect()`` reclaim
  working set, so it is the only probe that can confirm those releases actually
  freed memory.
* ``peak_rss_mb()`` — ``ru_maxrss``, a MONOTONIC high-water mark that never
  decreases within a process. Useful for "how close did we get to the ceiling",
  useless for observing reclamation.

Linux-only assumptions (``/proc``, ``ru_maxrss`` in KB) match the existing probe
this replaces. This module is a leaf: it imports ONLY the standard library (never
another ``jobs`` module) so ``main_scheduler`` and ``signal_job`` can both import
it without any circular-import risk.
"""
from __future__ import annotations

import resource


def current_rss_mb() -> float:
    """Current RSS (resident set size) in MB — what the process uses NOW.

    Prefers ``psutil`` (optional; not in requirements.txt, so usually absent in
    prod), falls back to ``/proc/self/statm`` on Linux, and returns ``0.0`` if
    neither source is available (never raises)."""
    try:
        import psutil  # optional; absent on the Render worker
        return psutil.Process().memory_info().rss / (1024.0 * 1024.0)
    except Exception:
        try:
            with open("/proc/self/statm") as fh:
                resident_pages = int(fh.read().split()[1])  # field 2 = resident pages
            return resident_pages * resource.getpagesize() / (1024.0 * 1024.0)
        except Exception:
            return 0.0


def peak_rss_mb() -> float:
    """Peak RSS in MB (``ru_maxrss`` high-water mark; KB on Linux)."""
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0
