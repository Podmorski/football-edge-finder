"""Recomputed monthly API budget for the widened, two-source schedule.

PART A2 / PART 3. The widening runs the sharp main line in every league where
**both** Mozzart and PS3838 publish a pre-match price, which shapes the request
profile:

* **PS3838** is fetched per league (one request per league *that has a fixture in
  the window* — the free Odds API events endpoint is the gate, so a league
  off-duty costs nothing).
* **Mozzart** moved from the per-league endpoint (empty on the free tier) to the
  **global** feed: a pass is ``ceil(events in window / 30)`` requests and is
  **shared by every league in the run** and cached for an hour, so its cost does
  not grow with the number of leagues — only with how often the sheet runs.
  Measured 2026-09-24: ~1 page for a 150-min pre-kickoff window, ~4 for a 24h
  window, 12 for an ad-hoc 3-day window; the daily sheet's calendar-day window is
  ~2-3.
* **The Odds API** stays a fallback (league-wide odds, 2 credits per league per
  run) plus **scores** for the widened leagues' settlement.

This module prints the projection and the margin for both providers. It makes no
external call: matches/week comes from the cached PS3838 schedule when present.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone

import ps3838_odds
import pulsescore_log
from core import league_registry

WEEKS_PER_MONTH = 30 / 7
FETCHES_PER_LEAGUE_WEEK = 2          # daily run + pre-kickoff run, on its matchday
RUNS_PER_WEEK = 10                   # 7 daily + ~3 pre-kickoff windows
MOZZART_PAGES_PER_PASS = 3           # global feed: blended over the run windows
MOZZART_TOPUP_PER_MONTH = 4 * WEEKS_PER_MONTH   # weekly top-up: 4 league-list pages/week
CLOSE_PER_MONTH = 60                 # PS3838 close: ~1 league per bet, ~15/week
ODDS_FALLBACK_PER_MONTH = 20         # PS3838 should cover every league
SCORES_PER_MONTH = 20                # 2 credits/league/day, few settling leagues
ODDS_CAP = 500
MIN_MARGIN = 0.20


def matches_per_week(slug: str) -> float | None:
    cached = ps3838_odds.load_cached(slug)
    if not cached:
        return None
    now = datetime.now(timezone.utc)
    horizon = now + timedelta(days=30)
    count = 0
    for event in cached["events"]:
        kickoff = ps3838_odds.event_kickoff(event)
        if kickoff is not None and now <= kickoff <= horizon:
            count += 1
    return count / (30 / 7)


def main() -> int:
    active = [slug for slug in league_registry.slug_of() if league_registry.is_active(slug)]
    total_mpw = 0.0
    print(f"{'league':<16}{'track':<12}{'matches/week':>14}")
    print("-" * 42)
    for slug in active:
        mpw = matches_per_week(slug)
        text = f"{mpw:.1f}" if mpw is not None else "n/a"
        if mpw:
            total_mpw += mpw
        print(f"{slug:<16}{league_registry.track_of(slug):<12}{text:>14}")
    print("-" * 42)
    print(f"{'TOTAL':<16}{len(active)} leagues{'':>2}{total_mpw:>12.1f}")

    ps_leagues = len(active) * FETCHES_PER_LEAGUE_WEEK * WEEKS_PER_MONTH
    mozzart = RUNS_PER_WEEK * WEEKS_PER_MONTH * MOZZART_PAGES_PER_PASS
    ps = ps_leagues + mozzart + MOZZART_TOPUP_PER_MONTH + CLOSE_PER_MONTH
    ps_margin = 1 - ps / pulsescore_log.MONTHLY_CAP
    odds = ODDS_FALLBACK_PER_MONTH + SCORES_PER_MONTH
    odds_margin = 1 - odds / ODDS_CAP

    print()
    print(f"PulseScore  : {ps:6.0f}/month of {pulsescore_log.MONTHLY_CAP} "
          f"-> margin {ps_margin:.1%}  [{'OK' if ps_margin >= MIN_MARGIN else 'TRIM THE SET'}]")
    print(f"              = {ps_leagues:5.0f} PS3838 ({len(active)} leagues x "
          f"{FETCHES_PER_LEAGUE_WEEK} fetch(es)/league/week x {WEEKS_PER_MONTH:.2f} weeks)")
    print(f"              + {mozzart:5.0f} Mozzart global feed ({RUNS_PER_WEEK} pass(es)/week "
          f"x {MOZZART_PAGES_PER_PASS} page(s)/pass x {WEEKS_PER_MONTH:.2f} weeks; "
          "one pass per run, shared by every league)")
    print(f"              + {MOZZART_TOPUP_PER_MONTH:5.0f} weekly league-list top-up "
          f"+ {CLOSE_PER_MONTH} PS3838 close")
    print(f"Odds API    : {odds:6.0f}/month of {ODDS_CAP} "
          f"-> margin {odds_margin:.1%}  [{'OK' if odds_margin >= MIN_MARGIN else 'TRIM THE SET'}]")
    print(f"              = {ODDS_FALLBACK_PER_MONTH} fallback odds + {SCORES_PER_MONTH} scores "
          f"(the fixture gate uses the free events endpoint)")
    print()
    print(f"rule: keep both margins >= {MIN_MARGIN:.0%}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
