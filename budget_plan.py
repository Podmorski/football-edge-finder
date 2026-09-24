"""Recomputed monthly API budget for the widened, two-source schedule.

PART A2. The widening runs the sharp main line in every league where **both**
Mozzart and PS3838 publish a pre-match price, which changes the request profile:

* **PulseScore** now serves *two* feeds per league (PS3838 sharp + Mozzart soft)
  and the fair sheet runs more often (daily **plus** a pre-kickoff run). Only a
  league with a **fixture in the window** is fetched — the free Odds API events
  endpoint is the gate — so a league off-duty costs nothing.
* **The Odds API** drops to a fallback (league-wide odds, 2 credits per league
  per run) plus **scores** for the widened leagues' settlement.

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
BOOKS = 2                            # PS3838 + Mozzart
MOZZART_IDS_PER_MONTH = 4 * WEEKS_PER_MONTH     # league list: 4 pages/week
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

    ps = (len(active) * FETCHES_PER_LEAGUE_WEEK * BOOKS * WEEKS_PER_MONTH
          + MOZZART_IDS_PER_MONTH + CLOSE_PER_MONTH)
    ps_margin = 1 - ps / pulsescore_log.MONTHLY_CAP
    odds = ODDS_FALLBACK_PER_MONTH + SCORES_PER_MONTH
    odds_margin = 1 - odds / ODDS_CAP

    print()
    print(f"PulseScore  : {ps:6.0f}/month of {pulsescore_log.MONTHLY_CAP} "
          f"-> margin {ps_margin:.1%}  [{'OK' if ps_margin >= MIN_MARGIN else 'TRIM THE SET'}]")
    print(f"              = {len(active)} leagues x {FETCHES_PER_LEAGUE_WEEK} "
          f"fetch(es)/league/week x {BOOKS} books x {WEEKS_PER_MONTH:.2f} weeks")
    print(f"                + {MOZZART_IDS_PER_MONTH:.0f} league-list + {CLOSE_PER_MONTH} close")
    print(f"Odds API    : {odds:6.0f}/month of {ODDS_CAP} "
          f"-> margin {odds_margin:.1%}  [{'OK' if odds_margin >= MIN_MARGIN else 'TRIM THE SET'}]")
    print(f"              = {ODDS_FALLBACK_PER_MONTH} fallback odds + {SCORES_PER_MONTH} scores "
          f"(the fixture gate uses the free events endpoint)")
    print()
    print(f"rule: keep both margins >= {MIN_MARGIN:.0%}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())