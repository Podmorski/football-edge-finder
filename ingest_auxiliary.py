"""Ingest AUXILIARY divisions E1 (Championship) and E3 (League Two).

These exist **only** to label League One newcomers. They are never in scope for
betting and are never used to fit a model.

Downloads via the existing football-data.co.uk path (penaltyblog's ``FootballData``
scraper), one request per file, and caches raw CSVs so a season is never
re-downloaded. Seasons 2014-15 .. 2022-23.
"""

from __future__ import annotations

import io
import sys
import time
from pathlib import Path

import pandas as pd
import requests

from core.normalise import coalesce_bom_columns

RAW_DIR = Path("data/auxiliary/raw")
OUT_DIR = Path("data/auxiliary")

# (label, football-data division code, penaltyblog competition key)
AUXILIARY = [
    ("e1", "E1", "ENG Championship"),
    ("e3", "E3", "ENG League 2"),
]

SEASONS = [f"{y}-{y + 1}" for y in range(2014, 2023)]  # 2014-15 .. 2022-23

URL = "https://www.football-data.co.uk/mmz4281/{code}/{div}.csv"
REQUEST_DELAY_SECONDS = 0.5
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/102.0.0.0 Safari/537.36"
    )
}


def season_code(season: str) -> str:
    a, b = season.split("-")
    return a[-2:] + b[-2:]


def download(div: str, season: str) -> str | None:
    url = URL.format(code=season_code(season), div=div)
    response = requests.get(url, headers=HEADERS, timeout=30)
    if response.status_code != 200:
        return None
    return response.text


def main() -> int:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    downloaded = 0
    cached = 0

    for label, div, competition in AUXILIARY:
        frames = []
        for season in SEASONS:
            cache = RAW_DIR / label / f"{season}.csv"
            if cache.exists():
                text = cache.read_text(encoding="utf-8", errors="replace")
                cached += 1
            else:
                text = download(div, season)
                time.sleep(REQUEST_DELAY_SECONDS)
                if text is None:
                    print(f"  {label} {season}: unavailable")
                    continue
                cache.parent.mkdir(parents=True, exist_ok=True)
                cache.write_text(text, encoding="utf-8")
                downloaded += 1

            df = pd.read_csv(io.StringIO(text))
            df = coalesce_bom_columns(df)
            df["team_home"] = df["HomeTeam"]
            df["team_away"] = df["AwayTeam"]
            df["season"] = season
            df["div"] = div
            df["auxiliary_division"] = label
            df["competition"] = competition
            frames.append(df)

        combined = pd.concat(frames, ignore_index=True)
        # Early seasons use 2-digit years; try both formats.
        parsed = pd.to_datetime(combined["Date"], format="%d/%m/%Y", errors="coerce")
        fallback = pd.to_datetime(combined["Date"], format="%d/%m/%y", errors="coerce")
        combined["date"] = parsed.fillna(fallback)
        # Two cached files carry a single fully-blank trailing row; drop it.
        blanks = int(combined["date"].isna().sum())
        if blanks:
            print(f"  {label}: dropping {blanks} blank row(s)")
            combined = combined[combined["date"].notna()].reset_index(drop=True)
        out = OUT_DIR / f"{label}.parquet"
        combined.to_parquet(out)
        print(
            f"{label} ({competition}): {len(combined)} rows, "
            f"seasons {combined['season'].min()}..{combined['season'].max()}, "
            f"dates {combined['date'].min().date()}..{combined['date'].max().date()} -> {out}"
        )

    print(f"\ndownloaded {downloaded}, reused {cached}")
    return 0


if __name__ == "__main__":
    sys.exit(main())