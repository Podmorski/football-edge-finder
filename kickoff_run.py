"""Pre-kickoff dispatcher — one fair-sheet run ~2h before each main kickoff window.

PART D1. The scheduler runs ``run.py kickoff-run`` every 20 minutes through the
playing hours. This job:

1. reads today's kickoffs for the active leagues from the **free** Odds API events
   endpoint (no credits);
2. clusters them into **main kickoff windows** (consecutive kickoffs less than
   ``CLUSTER_MINUTES`` apart, so a Saturday 13:00 block is one window);
3. runs the fair sheet with a **narrow pre-kickoff window** when ``now`` is about
   ``LEAD_MINUTES`` before a window opens, and does nothing otherwise.

So the sheet is refreshed minutes before the prices that matter, without a run
per match or a run on empty days.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone

import requests

import fair_sheet as fs
from core import league_registry

LEAD_MINUTES = 120
TOLERANCE_MINUTES = 20          # the dispatcher runs every 20 minutes
CLUSTER_MINUTES = 150           # kickoffs closer than this share a window
RUN_WINDOW_MINUTES = 150


def active_slugs() -> list[str]:
    return [slug for slug in league_registry.slug_of() if league_registry.is_active(slug)]


def today_kickoffs(session, key, now: datetime) -> list[datetime]:
    """UTC kickoffs later today across the active leagues (free events endpoint)."""
    day = now.astimezone().date()
    out: list[datetime] = []
    for slug in active_slugs():
        sport_key = league_registry.odds_api_key(slug)
        if sport_key is None:
            continue
        try:
            data, _headers = fs._call(session, key, f"/sports/{sport_key}/events",
                                      note="kickoff-run window discovery (free)")
        except Exception:  # noqa: BLE001
            continue
        for event in data if isinstance(data, list) else []:
            try:
                kickoff = fs.kickoff_utc(event["commence_time"])
            except (KeyError, ValueError):
                continue
            if kickoff > now and fs.local_date(event["commence_time"]) == day:
                out.append(kickoff)
    return sorted(out)


def windows(kickoffs: list[datetime]) -> list[datetime]:
    """The opening time of each main kickoff window."""
    openings: list[datetime] = []
    for kickoff in kickoffs:
        if not openings or kickoff - openings[-1] > timedelta(minutes=CLUSTER_MINUTES):
            openings.append(kickoff)
    return openings


def main(argv: list[str] | None = None) -> int:
    now = datetime.now(timezone.utc)
    session = requests.Session()
    try:
        key = fs.load_key()
    except SystemExit as exc:
        print(f"kickoff-run: {exc}")
        return 0
    kickoffs = today_kickoffs(session, key, now)
    openings = windows(kickoffs)
    print(f"kickoff-run {now.isoformat(timespec='minutes')}: {len(kickoffs)} kickoff(s) "
          f"later today in {len(openings)} window(s) "
          f"({', '.join(o.astimezone().strftime('%H:%M') for o in openings) or 'none'})")

    force = "--force" in (argv or sys.argv[1:])
    for opening in openings:
        lead = opening - timedelta(minutes=LEAD_MINUTES)
        if force or abs((lead - now).total_seconds()) <= TOLERANCE_MINUTES * 60:
            print(f"kickoff-run: window opens {opening.astimezone():%H:%M} — "
                  f"running the fair sheet (~{LEAD_MINUTES} min lead)")
            return fs.main(days=1, within_minutes=RUN_WINDOW_MINUTES)
    print("kickoff-run: no window is due now.")
    return 0


if __name__ == "__main__":
    sys.exit(main())