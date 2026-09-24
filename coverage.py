"""Mozzart ↔ PS3838 coverage record and the standing gap check.

PART 4 of the bug-check session. Each fair-sheet run records, per league it
actually fetched, how many matches each feed priced in the window. A league
where **PS3838 priced >= 5 matches but Mozzart returned 0** is a
**MOZZART COVERAGE GAP** — the local book may simply not have posted odds yet, or
the league id/name mapping drifted — and :mod:`health` surfaces it at the top of
``reports/health.md`` so it is caught before it silently shrinks the sample.

The record is written to ``data/mozzart/coverage.json`` (gitignored, recreated
every run) and read by the daily health job; neither side makes an API call.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

PATH = Path("data/mozzart/coverage.json")
GAP_MIN_PS = 5
STALE_HOURS = 48


def write(window, leagues: dict[str, dict], when: datetime | None = None) -> None:
    """Persist ``{slug: {"ps3838": n, "mozzart": m}}`` for the run's window."""
    PATH.parent.mkdir(parents=True, exist_ok=True)
    PATH.write_text(json.dumps({
        "updated": (when or datetime.now(timezone.utc)).isoformat(timespec="seconds"),
        "window": sorted(day.isoformat() for day in window),
        "leagues": leagues,
    }, ensure_ascii=False, indent=2), encoding="utf-8")


def load() -> dict | None:
    if not PATH.exists():
        return None
    try:
        return json.loads(PATH.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None


def _fresh(doc: dict, now: datetime | None = None) -> bool:
    try:
        updated = datetime.fromisoformat(doc["updated"])
    except (KeyError, ValueError):
        return False
    now = now or datetime.now(timezone.utc)
    return (now - updated).total_seconds() <= STALE_HOURS * 3600


def gaps(doc: dict | None = None, min_ps: int = GAP_MIN_PS,
         now: datetime | None = None) -> list[tuple[str, int]]:
    """[(slug, ps3838_count)] where PS3838 priced plenty and Mozzart priced none."""
    doc = doc if doc is not None else load()
    if not doc or not _fresh(doc, now):
        return []
    out: list[tuple[str, int]] = []
    for slug, counts in sorted((doc.get("leagues") or {}).items()):
        ps = int(counts.get("ps3838", 0))
        if ps >= min_ps and int(counts.get("mozzart", 0)) == 0:
            out.append((slug, ps))
    return out