"""Era-split and outlier diagnostics for the MAINLINE-HIST-1 B365/1X2 lead.

Read-only. No API calls. Reads the committed backtest bets CSV and the local
historical parquet, and prints:

  A2  B365/1X2 era split (2017-18..2018-19 vs 2019-20..2022-23): n, mean CLV
      with a matchday bootstrap 95% CI, and ROI; B365 1X2 margin per season;
      whether the pre-2019 B365 columns look like genuine book prices.
  A3  the 10 bets with the largest CLV (any book/market) with raw soft odds,
      Pinnacle pre-match, Pinnacle close, date and match; and the 1X2 rule's
      mean CLV with the CLV > 20% bets removed (sensitivity only).

Run:  ./venv/Scripts/python.exe research/era_split.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from step6_mainline_hist import bootstrap_ci  # noqa: E402

BETS = Path("reports/figures/mainline_hist_bets.csv")
HIST = Path("data/historical")
LEAGUES = ["bundesliga_1", "bundesliga_2", "league_one_t3", "ligue_2_t2"]

EARLY = {"2017-2018", "2018-2019"}
LATE = {"2019-2020", "2020-2021", "2021-2022", "2022-2023"}


def matchday(dates: pd.Series) -> pd.Series:
    d = pd.to_datetime(dates)
    return (d - pd.to_timedelta(d.dt.dayofweek, unit="D")).dt.strftime("%Y-%m-%d")


def era_block(frame: pd.DataFrame, label: str) -> dict:
    n = len(frame)
    if n == 0:
        return {"era": label, "n": 0}
    mean, lo, hi = bootstrap_ci(frame, "clv", lambda s: float(s.mean()), 2000, 20260924)
    return {
        "era": label, "n": n,
        "mean_clv": mean, "clv_lo": lo, "clv_hi": hi,
        "roi": float(frame["pnl"].mean()),
    }


def main() -> int:
    bets = pd.read_csv(BETS)
    bets["_matchday"] = matchday(bets["date"])

    print("=" * 78)
    print("A2  B365 / 1X2 era split")
    print("=" * 78)
    b = bets[(bets["soft_book"] == "b365") & (bets["market"] == "1X2")].copy()
    for label, seasons in (("2017-18..2018-19", EARLY), ("2019-20..2022-23", LATE)):
        block = era_block(b[b["season"].isin(seasons)], label)
        if block["n"]:
            print(f"  {label:<18} n={block['n']:<4} "
                  f"mean CLV {block['mean_clv']:+.2%} "
                  f"[{block['clv_lo']:+.2%}, {block['clv_hi']:+.2%}]  "
                  f"ROI {block['roi']:+.2%}")
        else:
            print(f"  {label:<18} n=0")

    print("\n  B365 1X2 margin per season (mean over all four leagues):")
    frames = []
    for slug in LEAGUES:
        path = HIST / f"{slug}.parquet"
        if not path.exists():
            continue
        df = pd.read_parquet(path)
        cols = ["b365_h", "b365_d", "b365_a"]
        if not all(c in df.columns for c in cols):
            continue
        block = df[["season", *cols]].copy()
        block[cols] = block[cols].astype(float)
        block = block[(block[cols] > 1.0).all(axis=1)]
        block["margin"] = (1 / block["b365_h"] + 1 / block["b365_d"]
                           + 1 / block["b365_a"] - 1.0)
        block["league"] = slug
        frames.append(block)
    margins = pd.concat(frames, ignore_index=True)
    for season in sorted(margins["season"].unique()):
        row = margins[margins["season"] == season]
        print(f"    {season:<10} n={len(row):<5} mean margin {row['margin'].mean():+.4f}")

    print("\n  Pre-2019 B365 vs PS / BbAv (are the B365 columns genuine book prices?):")
    for slug in LEAGUES:
        path = HIST / f"{slug}.parquet"
        if not path.exists():
            continue
        df = pd.read_parquet(path)
        df = df[df["season"].isin(EARLY)]
        need = ["b365_h", "b365_d", "b365_a", "psh", "psd", "psa",
                "bb_av_h", "bb_av_d", "bb_av_a"]
        if not all(c in df.columns for c in need):
            continue
        block = df[need].astype(float).dropna()
        block = block[(block > 1.0).all(axis=1)]
        if block.empty:
            continue
        b365_m = (1 / block["b365_h"] + 1 / block["b365_d"] + 1 / block["b365_a"] - 1)
        ps_m = (1 / block["psh"] + 1 / block["psd"] + 1 / block["psa"] - 1)
        bb_m = (1 / block["bb_av_h"] + 1 / block["bb_av_d"] + 1 / block["bb_av_a"] - 1)
        identical_ps = (block["b365_h"] == block["psh"]).mean()
        identical_bb = (block["b365_h"] == block["bb_av_h"]).mean()
        print(f"    {slug:<16} n={len(block):<4} "
              f"margin b365 {b365_m.mean():+.4f} ps {ps_m.mean():+.4f} "
              f"bbAv {bb_m.mean():+.4f} | b365_h==psh {identical_ps:.1%} "
              f"b365_h==bbAv_h {identical_bb:.1%}")

    print("\n" + "=" * 78)
    print("A3  Outliers: 10 largest CLV (any book/market)")
    print("=" * 78)
    raw = {}
    for slug in LEAGUES:
        path = HIST / f"{slug}.parquet"
        if not path.exists():
            continue
        df = pd.read_parquet(path)
        df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
        df["league"] = slug
        raw[slug] = df
    allraw = pd.concat(raw.values(), ignore_index=True)

    top = bets.sort_values("clv", ascending=False).head(10).copy()
    merged = top.merge(
        allraw[["date", "league", "team_home", "team_away",
                "psh", "psd", "psa", "psch", "pscd", "psca"]],
        left_on=["date", "league", "home", "away"],
        right_on=["date", "league", "team_home", "team_away"],
        how="left",
    )
    print(f"  {'date':<11}{'match':<34}{'mkt':<6}{'sel':<7}"
          f"{'soft':>7}{'PSpre':>8}{'PSclose':>9}{'clv':>9}")
    for r in merged.itertuples(index=False):
        ps_pre = f"{r.psh:.2f}/{r.psd:.2f}/{r.psa:.2f}" if pd.notna(r.psh) else "n/a"
        ps_cls = f"{r.psch:.2f}/{r.pscd:.2f}/{r.psca:.2f}" if pd.notna(r.psch) else "n/a"
        match = f"{r.home} v {r.away}"[:33]
        print(f"  {r.date:<11}{match:<34}{r.market:<6}{r.selection:<7}"
              f"{r.soft_odds:>7.2f}{ps_pre:>8}{ps_cls:>9}{r.clv:>+9.1%}")

    print("\n  Sensitivity: 1X2 rule mean CLV excluding bets with CLV > 20%")
    one = bets[(bets["soft_book"] == "b365") & (bets["market"] == "1X2")].copy()
    trimmed = one[one["clv"] <= 0.20]
    mean, lo, hi = bootstrap_ci(trimmed, "clv", lambda s: float(s.mean()), 2000, 20260924)
    print(f"    all      n={len(one):<4} mean CLV {one['clv'].mean():+.2%}")
    print(f"    trimmed  n={len(trimmed):<4} mean CLV {mean:+.2%} [{lo:+.2%}, {hi:+.2%}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())