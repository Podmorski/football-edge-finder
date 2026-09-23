"""Refresh the current season's historical results for every in-scope league.

Source: football-data.co.uk via penaltyblog. Makes **no API-Football calls**.

Re-pulls only the *current* season, merges it into each league's parquet under
``data/historical/``, and de-duplicates on ``(date, team_home, team_away)``.
Safe to run repeatedly: a second run with no new matches adds 0 rows.
"""

from __future__ import annotations

import sys
import time
import warnings
from datetime import date
from pathlib import Path

import pandas as pd

from core.normalise import coalesce_bom_columns
from leagues import LEAGUES, label_of
from penaltyblog.scrapers import FootballData

# penaltyblog builds frames via repeated inserts; the resulting warnings are
# noise for our purposes.
warnings.filterwarnings("ignore", category=pd.errors.PerformanceWarning)

DATA_DIR = Path("data/historical")
DEDUP_KEYS = ["date", "team_home", "team_away"]
REQUEST_DELAY_SECONDS = 0.5


def current_season(today: date) -> str:
    """European season label, e.g. 2026-2027 (seasons start in July)."""
    if today.month >= 7:
        return f"{today.year}-{today.year + 1}"
    return f"{today.year - 1}-{today.year}"


def refresh_league(league: dict, season: str) -> tuple[int, object, object, int]:
    """Merge the current season into the league's parquet. Returns summary."""
    path = DATA_DIR / f"{league['slug']}.parquet"
    existing = pd.read_parquet(path) if path.exists() else pd.DataFrame()
    existing = coalesce_bom_columns(existing) if not existing.empty else existing
    before = len(existing)

    try:
        fresh = FootballData(league["penaltyblog"], season).get_fixtures()
        time.sleep(REQUEST_DELAY_SECONDS)
    except Exception as exc:  # noqa: BLE001 - report and continue
        print(f"    current season {season}: unavailable ({type(exc).__name__})")
        fresh = pd.DataFrame()

    if fresh is None or fresh.empty:
        dates = pd.to_datetime(existing["date"], errors="coerce") if not existing.empty else pd.Series(dtype="datetime64[ns]")
        return 0, (dates.max() if not dates.empty else None), before, before

    if existing.empty:
        combined = fresh
    else:
        combined = pd.concat([existing, fresh])

    combined = combined.reset_index()
    combined = combined.drop_duplicates(subset=DEDUP_KEYS, keep="last")
    combined = combined.set_index("id")

    added = len(combined) - before
    newest = pd.to_datetime(combined["date"], errors="coerce").max()

    combined = coalesce_bom_columns(combined)
    path.parent.mkdir(parents=True, exist_ok=True)
    combined.to_parquet(path)
    return added, newest, before, len(combined)


def main() -> int:
    season = current_season(date.today())
    print(f"Current season: {season}\n")

    results = []
    for league in LEAGUES:
        print(f"=== {label_of(league)} ===")
        added, newest, before, after = refresh_league(league, season)
        newest_str = newest.date() if newest is not None and not pd.isna(newest) else "n/a"
        print(f"  rows added: {added} | newest match date: {newest_str} | total rows: {after}")
        results.append((label_of(league), added, newest_str, before, after))
        print()

    print("=== SUMMARY (refresh) ===")
    total_added = 0
    for label, added, newest_str, before, after in results:
        total_added += max(added, 0)
        print(f"{label}: +{added} rows | newest {newest_str} | {before} -> {after}")
    print(f"\nTotal rows added this run: {total_added}")
    return 0


if __name__ == "__main__":
    sys.exit(main())