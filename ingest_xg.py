"""Understat xG coverage test via penaltyblog.

Source: https://understat.com/ (public endpoints, no auth).
Access method: penaltyblog's ``Understat`` scraper (``get_fixtures``), which
hits Understat's ``getLeagueData`` JSON endpoint.

This is deliberately a *coverage test*, not a bug hunt: a league returning
nothing is a valid outcome and is reported plainly. Understat only covers a
handful of top divisions, so gaps are expected.

Output: one parquet file per league that returns data, under ``data/xg/``.
"""

from __future__ import annotations

import sys
import time
import warnings
from pathlib import Path

import pandas as pd

from penaltyblog.scrapers import Understat

# penaltyblog builds frames via repeated inserts; the resulting warnings are
# noise for our purposes.
warnings.filterwarnings("ignore", category=pd.errors.PerformanceWarning)

DATA_DIR = Path("data/xg")

# Leagues from CONFIG. ``understat`` is the competition key understood by
# penaltyblog's Understat scraper (None = not covered by Understat).
LEAGUES = [
    {
        "name": "Bundesliga",
        "api_football_id": 79,
        "understat": "DEU Bundesliga 1",
        "slug": "bundesliga",
    },
    {
        "name": "League One",
        "api_football_id": 41,
        "understat": None,
        "slug": "league_one",
    },
    {
        "name": "Serbian SuperLiga",
        "api_football_id": 287,
        "understat": None,
        "slug": "serbian_superliga",
    },
]

SEASONS = [f"{year}-{year + 1}" for year in range(2015, 2027)]

REQUEST_DELAY_SECONDS = 0.5


def fetch_league(competition: str) -> tuple[pd.DataFrame, list[str]]:
    """Return (concatenated frame, list of per-season status strings)."""
    frames: list[pd.DataFrame] = []
    notes: list[str] = []
    for season in SEASONS:
        try:
            df = Understat(competition, season).get_fixtures()
        except Exception as exc:  # noqa: BLE001 - coverage test: report and move on
            notes.append(f"{season}: no data ({type(exc).__name__})")
            time.sleep(REQUEST_DELAY_SECONDS)
            continue

        if df is None or df.empty:
            notes.append(f"{season}: empty")
        else:
            notes.append(f"{season}: {len(df)} rows")
            frames.append(df)
        time.sleep(REQUEST_DELAY_SECONDS)

    if not frames:
        return pd.DataFrame(), notes
    return pd.concat(frames).sort_index(), notes


def main() -> int:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    summary: list[tuple[str, str, int | None, object, object]] = []

    for league in LEAGUES:
        print(f"\n=== {league['name']} (api_football_id={league['api_football_id']}) ===")

        if league["understat"] is None:
            print("  NOT COVERED by Understat — no xG available from this source.")
            summary.append((league["name"], "not covered", None, None, None))
            continue

        df, notes = fetch_league(league["understat"])
        for note in notes:
            print(f"    {note}")

        if df.empty:
            print("  RESULT: no xG data returned for any season.")
            summary.append((league["name"], "no data", 0, None, None))
            continue

        out_path = DATA_DIR / f"{league['slug']}.parquet"
        df.to_parquet(out_path)

        dates = pd.to_datetime(df["datetime"], errors="coerce")
        summary.append((league["name"], "success", len(df), dates.min(), dates.max()))
        print(f"  RESULT: success — saved {len(df)} rows -> {out_path}")

    print("\n=== SUMMARY (Understat xG coverage) ===")
    for name, status, rows, date_min, date_max in summary:
        if status == "success":
            print(f"{name}: SUCCESS — {rows} rows, {date_min.date()} .. {date_max.date()}")
        elif status == "not covered":
            print(f"{name}: NOT COVERED by Understat")
        else:
            print(f"{name}: NO DATA returned")

    return 0


if __name__ == "__main__":
    sys.exit(main())
