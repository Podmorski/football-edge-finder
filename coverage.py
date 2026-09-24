"""Mozzart ↔ PS3838 coverage record and the standing gap checks.

PART 4 of the bug-check session. Each fair-sheet run records, per league it
actually fetched, how many matches each feed priced in the window and how many of
them **joined** (a Mozzart event matched to the PS3838 match). Two alarms are
derived from that record:

* **MOZZART COVERAGE GAP** — a league where PS3838 priced >= 3 matches but Mozzart
  returned 0 (the local book may not have posted odds yet, or the league label
  mapping drifted);
* **ZERO JOINS** — *no* league joined at all while PS3838 priced >= 5 matches in
  the window, i.e. the Mozzart feed itself is empty or every label has drifted.

:mod:`health` surfaces both at the top of ``reports/health.md`` so they are caught
before they silently shrink the sample.

The record is written to ``data/mozzart/coverage.json`` (gitignored, recreated
every run) and read by the daily health job; neither side makes an API call.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

PATH = Path("data/mozzart/coverage.json")
GAP_MIN_PS = 3
ZERO_JOIN_MIN_PS = 5
STALE_HOURS = 48


def write(window, leagues: dict[str, dict], when: datetime | None = None) -> dict:
    """Persist ``{slug: {"ps3838": n, "mozzart": m, "joined": j}}``; return the doc."""
    PATH.parent.mkdir(parents=True, exist_ok=True)
    doc = {
        "updated": (when or datetime.now(timezone.utc)).isoformat(timespec="seconds"),
        "window": sorted(day.isoformat() for day in window),
        "leagues": leagues,
    }
    PATH.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    return doc


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


def zero_joins(doc: dict | None = None, min_ps: int = ZERO_JOIN_MIN_PS,
               now: datetime | None = None) -> int:
    """The PS3838 match total when *no* league joined, else 0.

    A run where Mozzart and PS3838 shared **no** match across every league, while
    PS3838 priced at least ``min_ps`` matches, means the Mozzart feed is empty or
    every league label has drifted — a louder failure than a single-league gap.
    """
    doc = doc if doc is not None else load()
    if not doc or not _fresh(doc, now):
        return 0
    leagues = doc.get("leagues") or {}
    ps = sum(int(counts.get("ps3838", 0)) for counts in leagues.values())
    joined = sum(int(counts.get("joined", 0)) for counts in leagues.values())
    return ps if joined == 0 and ps >= min_ps else 0