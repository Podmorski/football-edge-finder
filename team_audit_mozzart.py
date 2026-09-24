"""Cross-source team-name audit: Mozzart <-> The Odds API <-> historical.

Local only — no network calls. Reads the historical parquet, the Odds API
fair-sheet snapshots (``data/odds_snapshots/oddsapi/fair_sheet/``) and the raw
Mozzart events (``data/mozzart/raw/``), and reports every name that does not
match a historical name at the project's similarity threshold. A miss is
**reported, never guessed**; add an alias to ``config/team_aliases.yaml`` only
when a report shows a real variant.

Run:  ./venv/Scripts/python.exe team_audit_mozzart.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

from core.team_names import MATCH_SIMILARITY, best_match
from leagues import LEAGUES

HIST = Path("data/historical")
ODDS_CACHE = Path("data/odds_snapshots/oddsapi/fair_sheet")
MOZZART_RAW = Path("data/mozzart/raw")

# Mozzart Serbian league name -> our slug (see config/mozzart_market_map.yaml and
# the PulseScore discovery note in docs/PROJECT_PLAN.md).
MOZZART_LEAGUES = {
    "Nemačka 1": "bundesliga_1",
    "Nemačka 2": "bundesliga_2",
    "Engleska 3": "league_one_t3",
    "Francuska 2": "ligue_2_t2",
}

# The Odds API sport key -> our slug (mirrors fair_sheet.SPORTS).
ODDS_SPORTS = {
    "soccer_germany_bundesliga": "bundesliga_1",
    "soccer_germany_bundesliga2": "bundesliga_2",
    "soccer_england_league1": "league_one_t3",
    "soccer_france_ligue_two": "ligue_2_t2",
}


def historical_names(slug: str) -> set[str]:
    path = HIST / f"{slug}.parquet"
    if not path.exists():
        return set()
    df = pd.read_parquet(path)
    return set(df["team_home"].dropna()) | set(df["team_away"].dropna())


def odds_api_names() -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    if not ODDS_CACHE.exists():
        return out
    for path in ODDS_CACHE.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))["data"]
        except (ValueError, KeyError, OSError):
            continue
        events = data if isinstance(data, list) else [data]
        for event in events:
            if not isinstance(event, dict) or not event.get("home_team"):
                continue
            slug = ODDS_SPORTS.get(event.get("sport_key", ""))
            if slug is None:
                continue
            out.setdefault(slug, set()).update(
                {event["home_team"], event["away_team"]})
    return out


def mozzart_names() -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    if not MOZZART_RAW.exists():
        return out
    for path in MOZZART_RAW.glob("soccer_events_*.json"):
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            continue
        event = doc.get("data") if isinstance(doc, dict) else None
        if not isinstance(event, dict) or not event.get("home"):
            continue
        slug = MOZZART_LEAGUES.get(event.get("league", ""))
        if slug is None:
            continue
        out.setdefault(slug, set()).update({event["home"], event["away"]})
    return out


def best_match_name(name: str, candidates: set[str]) -> tuple[str | None, float]:
    return best_match(name, candidates)


def audit_source(label: str, names: dict[str, set[str]]) -> int:
    print(f"\n## {label}")
    unmapped = 0
    for league in LEAGUES:
        slug = league["slug"]
        source = names.get(slug)
        if not source:
            continue
        history = historical_names(slug)
        if not history:
            print(f"  {slug}: no historical data — skipped")
            continue
        misses = []
        for name in sorted(source):
            _match, score = best_match_name(name, history)
            if score < MATCH_SIMILARITY:
                misses.append((name, score))
        print(f"  {slug}: {len(source)} names, {len(misses)} unmapped")
        for name, score in misses:
            print(f"    UNMAPPED {name!r} (best {score:.2f})")
        unmapped += len(misses)
    return unmapped


def main() -> int:
    print("=" * 72)
    print("Cross-source team-name audit (Mozzart / Odds API / historical)")
    print("=" * 72)
    total = 0
    total += audit_source("The Odds API", odds_api_names())
    total += audit_source("Mozzart", mozzart_names())
    print(f"\nTotal unmapped names: {total}")
    if total == 0:
        print("Every name matched a historical name at the threshold.")
    print("\nA miss is reported, never guessed. Add an alias to "
          "config/team_aliases.yaml only with evidence.")
    return 0


if __name__ == "__main__":
    sys.exit(main())