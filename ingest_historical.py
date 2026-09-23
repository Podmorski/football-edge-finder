"""Ingest historical match results from football-data.co.uk via penaltyblog.

Source: https://www.football-data.co.uk/ (free, public CSV downloads, no auth).
Access method: penaltyblog's ``FootballData`` scraper, which fetches the
per-season CSV for a given competition slug.

Output: one parquet file per league under ``data/historical/``, named by the
league's tier-qualified slug (e.g. ``bundesliga_2.parquet`` for 2. Bundesliga).

Tier labelling: every league entry carries an explicit ``tier`` so that
same-named divisions in different tiers (e.g. Bundesliga vs 2. Bundesliga)
can never be confused. Top-flight Bundesliga is deliberately NOT ingested here.

Note on coverage: penaltyblog's football-data.co.uk scraper only maps a fixed
set of competitions. Any league not in that set is reported as unavailable
rather than silently skipped.
"""

from __future__ import annotations

import sys
import time
import warnings
from pathlib import Path

import pandas as pd

from core.normalise import coalesce_bom_columns
from leagues import LEAGUES, label_of
from penaltyblog.scrapers import FootballData

# penaltyblog builds frames via repeated inserts; the resulting warnings are
# noise for our purposes.
warnings.filterwarnings("ignore", category=pd.errors.PerformanceWarning)

DATA_DIR = Path("data/historical")

# League registry (tier/role labelled) lives in leagues.py.

# Seasons to attempt. football-data.co.uk coverage varies by league/season;
# missing seasons are reported and skipped.
SEASONS = [f"{year}-{year + 1}" for year in range(2015, 2027)]

# Small politeness delay between HTTP requests.
REQUEST_DELAY_SECONDS = 0.5


def fetch_league(competition: str) -> pd.DataFrame:
    """Fetch and concatenate all available seasons for one competition."""
    frames: list[pd.DataFrame] = []
    for season in SEASONS:
        try:
            df = FootballData(competition, season).get_fixtures()
        except Exception as exc:  # noqa: BLE001 - report per-season and continue
            print(f"    {season}: unavailable ({type(exc).__name__})")
            time.sleep(REQUEST_DELAY_SECONDS)
            continue

        if df is None or df.empty:
            print(f"    {season}: empty")
        else:
            print(f"    {season}: {len(df)} rows")
            frames.append(df)
        time.sleep(REQUEST_DELAY_SECONDS)

    if not frames:
        return pd.DataFrame()
    return pd.concat(frames).sort_index()


def main() -> int:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    summary: list[tuple[str, int | None, object, object]] = []

    for league in LEAGUES:
        label = label_of(league)
        print(f"\n=== {label} | api_football_id={league['api_football_id']} ===")

        if league["penaltyblog"] is None:
            print("  NOT COVERED by penaltyblog's football-data.co.uk scraper.")
            summary.append((label, None, None, None))
            continue

        df = fetch_league(league["penaltyblog"])
        if df.empty:
            print("  no data retrieved")
            summary.append((label, 0, None, None))
            continue

        out_path = DATA_DIR / f"{league['slug']}.parquet"
        df = coalesce_bom_columns(df)
        df.to_parquet(out_path)

        dates = pd.to_datetime(df["date"], errors="coerce")
        summary.append((label, len(df), dates.min(), dates.max()))
        print(f"  saved {len(df)} rows -> {out_path}")

    print("\n=== SUMMARY (historical) ===")
    for label, rows, date_min, date_max in summary:
        if rows is None:
            print(f"{label}: NOT AVAILABLE from source")
        elif rows == 0:
            print(f"{label}: 0 rows")
        else:
            print(f"{label}: {rows} rows, {date_min.date()} .. {date_max.date()}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
