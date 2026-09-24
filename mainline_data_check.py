"""STEP 2 — data check for MAINLINE-HIST-1.

Two questions, per league x season and per market (1X2, O/U 2.5, AH main line):

1. **Coverage** — what share of matches has the Pinnacle pre-match price *and*
   each soft book, so we know what the backtest can actually see.
2. **Comparability** — the median absolute **implied-probability gap** between
   Pinnacle and each soft book. If the two feeds were quoting different matches or
   different times, the gaps would be far larger than a book's margin; this is the
   check that they are comparable snapshots.

The gap is reported twice: **raw** (``|1/odds_pin - 1/odds_soft|``, which contains
both the margin difference and the disagreement) and **de-margined** (the power
method applied separately to each side, which isolates the disagreement).

Local data only: no network, no API calls.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

from core import odds

LEAGUES = ["bundesliga_1", "bundesliga_2", "league_one_t3", "ligue_2_t2"]
SEASONS = ["2017-2018", "2018-2019", "2019-2020", "2020-2021", "2021-2022", "2022-2023"]
OUT = Path("reports/figures/mainline_hist_data_check.csv")

# market -> (pinnacle columns, soft columns per book)
MARKETS: dict[str, tuple[tuple[str, ...], dict[str, tuple[str, ...]]]] = {
    "1X2": (("psh", "psd", "psa"),
            {"b365": ("b365_h", "b365_d", "b365_a"),
             "average": ("avg_h", "avg_d", "avg_a"),
             "average_fallback": ("bb_av_h", "bb_av_d", "bb_av_a")}),
    "OU2.5": (("p>2.5", "p<2.5"),
              {"b365": ("b365>2.5", "b365<2.5"),
               "average": ("avg>2.5", "avg<2.5"),
               "average_fallback": ("bb_av>2.5", "bb_av<2.5")}),
    "AH": (("pahh", "paha"),
           {"b365": ("b365_ahh", "b365_aha"),
            "average": ("avg_ahh", "avg_aha"),
            "average_fallback": ("bb_av_ahh", "bb_av_aha")}),
}


def frame(slug: str) -> pd.DataFrame:
    """Discovery-season rows of one league, on a plain RangeIndex.

    The parquet index is a match-id string; left in place, a boolean Series would
    align against the *columns* in ``DataFrame.where`` and silently produce NaN.
    """
    df = pd.read_parquet(Path("data/historical") / f"{slug}.parquet")
    return df[df["season"].isin(SEASONS)].reset_index(drop=True)


def soft(block: pd.DataFrame, cols: dict[str, tuple[str, ...]], book: str) -> pd.DataFrame:
    """The soft prices for ``book``, falling back to BbAv for the average series."""
    primary = block[list(cols[book])].astype(float)
    if book != "average":
        return primary
    fallback = block[list(cols["average_fallback"])].astype(float)
    return primary.where(primary.notna().all(axis=1), fallback)


def row_for(block: pd.DataFrame, market: str, league: str, season: str) -> dict:
    cols, books = MARKETS[market]
    if not all(c in block.columns for c in cols):
        return {}
    pin = block[list(cols)].astype(float)
    pin_ok = pin.notna().all(axis=1)
    record = {"league": league, "season": season, "market": market, "n_rows": len(block),
              "n_pinnacle": int(pin_ok.sum())}
    demargined_pin = odds.demargin(pin.where(pin_ok), "power")
    for book in ("b365", "average"):
        block_soft = soft(block, books, book)
        both = pin_ok & block_soft.notna().all(axis=1)
        record[f"n_{book}"] = int(both.sum())
        record[f"share_{book}"] = (round(100.0 * both.mean(), 1) if len(block) else np.nan)
        if both.any():
            # NumPy on the masked rows. A pandas subtraction here would align on the
            # COLUMN names too, and `psh/psd/psa` vs `b365_h/...` have none in common.
            mask = both.to_numpy()
            raw_gap = np.abs(1.0 / pin.to_numpy()[mask] - 1.0 / block_soft.to_numpy()[mask])
            dem = odds.demargin(block_soft, "power").to_numpy()[mask]
            dem_gap = np.abs(demargined_pin.to_numpy()[mask] - dem)
            record[f"median_raw_gap_{book}"] = float(np.median(raw_gap))
            record[f"median_demargined_gap_{book}"] = float(np.median(dem_gap))
        else:
            record[f"median_raw_gap_{book}"] = np.nan
            record[f"median_demargined_gap_{book}"] = np.nan
    return record


def main() -> int:
    rows: list[dict] = []
    for slug in LEAGUES:
        block = frame(slug)
        for season in SEASONS:
            sub = block[block["season"] == season]
            if sub.empty:
                continue
            for market in MARKETS:
                record = row_for(sub, market, slug, season)
                if record:
                    rows.append(record)

    table = pd.DataFrame(rows)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    table.to_csv(OUT, index=False)

    print("=" * 108)
    print("STEP 2 data check — coverage of the MAINLINE-HIST-1 inputs (discovery seasons)")
    print("=" * 108)
    print(f"{'market':<7}{'league':<15}{'season':<11}{'rows':>6}{'pin':>6}"
          f"{'b365':>7}{'b365%':>7}{'avg%':>7}{'rawGapB':>10}{'demGapB':>10}{'rawGapA':>10}")
    for r in table.itertuples(index=False):
        print(f"{r.market:<7}{r.league:<15}{r.season:<11}{r.n_rows:>6}{r.n_pinnacle:>6}"
              f"{r.n_b365:>7}{r.share_b365:>7.1f}{r.share_average:>7.1f}"
              f"{r.median_raw_gap_b365:>10.4f}{r.median_demargined_gap_b365:>10.4f}"
              f"{r.median_raw_gap_average:>10.4f}")

    print("\n--- pooled by market (all leagues, all discovery seasons) ---")
    print(f"{'market':<7}{'rows':>7}{'pin%':>7}{'b365%':>7}{'avg%':>7}"
          f"{'rawGapB365':>12}{'demGapB365':>12}{'rawGapAvg':>11}{'demGapAvg':>11}")
    for market, sub in table.groupby("market"):
        print(f"{market:<7}{sub['n_rows'].sum():>7}"
              f"{100 * sub['n_pinnacle'].sum() / sub['n_rows'].sum():>7.1f}"
              f"{100 * sub['n_b365'].sum() / sub['n_rows'].sum():>7.1f}"
              f"{100 * sub['n_average'].sum() / sub['n_rows'].sum():>7.1f}"
              f"{sub['median_raw_gap_b365'].median():>12.4f}"
              f"{sub['median_demargined_gap_b365'].median():>12.4f}"
              f"{sub['median_raw_gap_average'].median():>11.4f}"
              f"{sub['median_demargined_gap_average'].median():>11.4f}")

    print("\nread: a de-margined gap of a few tenths of a percent is a comparable")
    print("snapshot; a gap of several percent would mean the feeds are not quoting")
    print("the same thing and the test would be invalid.")
    print(f"\nwrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
