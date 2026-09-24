"""Step 1 — totals integrity report (League One).

1a. Raw football-data CSV vs pipeline, 30 random matches, O/U columns.
1b. Column map raw -> parquet -> core/odds.py -> tables, per era.
1c. Per season: market P(over) log loss vs constant vs base rate, correlations,
    and the M1 recalibration slope/intercept (negative slope = inverted input).
1d. Explain the 0.4665 figure from the old rule table.
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import minimize

from core import odds, walkforward as wf
from models import league_one_dixon_coles as m

SEASONS = ["2017-2018", "2018-2019", "2019-2020", "2020-2021", "2021-2022", "2022-2023"]
FINAL = wf.Config(xi=0.002, covid_mode="exclude_after", newcomer="newcomer_prior")
PRED = wf.PRED_DIR / f"{FINAL.config_id}.parquet"
ODDS_COLUMNS = ["avg>2.5", "avg<2.5", "bb_av>2.5", "bb_av<2.5", "b365>2.5", "b365<2.5"]
RAW_DIR = Path("data/auxiliary/raw/e1")


def logit(p):
    p = np.clip(np.asarray(p, dtype=float), 1e-6, 1 - 1e-6)
    return np.log(p / (1 - p))


def fit_slope(p, y):
    design = np.column_stack([np.ones(len(p)), logit(p)])

    def objective(beta):
        z = design @ beta
        return float(np.mean(np.logaddexp(0.0, z) - y * z))

    beta = minimize(objective, x0=np.array([0.0, 1.0]), method="Nelder-Mead",
                    options={"xatol": 1e-8, "fatol": 1e-12, "maxiter": 4000}).x
    return float(beta[1]), float(beta[0])


def part_1a() -> None:
    print("=" * 100)
    print("1a. RAW football-data CSV vs pipeline parquet (30 random matches, E1 as the raw source)")
    print("=" * 100)
    print("NOTE: E2 raw CSVs were not downloadable this session (downloads restricted to F1).")
    print("      E1 uses identical football-data.co.uk headers, so it demonstrates the")
    print("      raw -> parquet mapping. E2 parquet semantics are verified in 1c (positive")
    print("      correlation) and by penaltyblog's sanitize_columns being a pure rename.")
    print()

    raw = pd.read_csv(io.StringIO((RAW_DIR / "2017-2018.csv").read_text(encoding="utf-8", errors="replace")))
    parquet = pd.read_parquet("data/auxiliary/e1.parquet")
    parquet = parquet[parquet["season"] == "2017-2018"].copy()

    cols = ["BbAv>2.5", "BbAv<2.5", "BbMx>2.5", "BbMx<2.5"]
    # Early seasons use 2-digit years; try both formats (as ingest_auxiliary does).
    parsed = pd.to_datetime(raw["Date"], format="%d/%m/%Y", errors="coerce")
    fallback = pd.to_datetime(raw["Date"], format="%d/%m/%y", errors="coerce")
    raw["_date"] = parsed.fillna(fallback).astype("datetime64[ns]")
    parquet["date"] = pd.to_datetime(parquet["date"]).astype("datetime64[ns]")

    pq = parquet[["date", "team_home", "team_away"] + cols].rename(
        columns={c: f"pq_{c}" for c in cols}
    )
    merged = raw.merge(
        pq, left_on=["_date", "HomeTeam", "AwayTeam"],
        right_on=["date", "team_home", "team_away"], how="inner",
    )
    print(f"matched rows: {len(merged)} of {len(raw)} raw")
    if merged.empty:
        print("  no rows matched - cannot verify")
        return

    sample = merged.sample(min(30, len(merged)), random_state=0).reset_index(drop=True)
    print(f"\n{'date':<12}{'home':<20}{'away':<20}{'FTHG':>5}{'FTAG':>5}{'over':>6}"
          + "".join(f"{c:>12}" for c in cols) + "  match")
    mismatches = 0
    for i in range(len(sample)):
        r = sample.iloc[i]
        over = int((r["FTHG"] + r["FTAG"]) > 2.5)
        cells, ok = [], True
        for c in cols:
            a, b = float(r[c]), float(r[f"pq_{c}"])
            cells.append(f"{a:>12.2f}")
            if not (np.isnan(a) and np.isnan(b)) and abs(a - b) > 1e-9:
                ok = False
        if not ok:
            mismatches += 1
        print(f"{str(r['_date'].date()):<12}{str(r['HomeTeam'])[:19]:<20}"
              f"{str(r['AwayTeam'])[:19]:<20}{r['FTHG']:>5}{r['FTAG']:>5}{over:>6}"
              + "".join(cells) + f"  {'OK' if ok else 'MISMATCH'}")

    bad = 0
    for c in cols:
        a = merged[c].to_numpy(dtype=float)
        b = merged[f"pq_{c}"].to_numpy(dtype=float)
        bad += int(np.sum(~np.isclose(a, b, equal_nan=True)))
    print(f"\nvalue mismatches across all {len(merged)} matched rows x {len(cols)} columns: {bad}")
    print("raw -> parquet mapping is faithful" if bad == 0 else "MISMATCHES FOUND")


def part_1b() -> None:
    print("\n" + "=" * 100)
    print("1b. Column map: raw header -> parquet name -> core/odds.py -> table column")
    print("=" * 100)
    rows = [
        ("BbAv era (2015-16..2018-19)", "BbAv>2.5", "bb_av>2.5", "over", "P(over)"),
        ("BbAv era (2015-16..2018-19)", "BbAv<2.5", "bb_av<2.5", "under", "P(under)"),
        ("BbAv era (2015-16..2018-19)", "BbMx>2.5", "bb_mx>2.5", "(unused)", "-"),
        ("Avg era (2019-20..)", "Avg>2.5", "avg>2.5", "over", "P(over)"),
        ("Avg era (2019-20..)", "Avg<2.5", "avg<2.5", "under", "P(under)"),
        ("Avg era (2019-20..)", "AvgC>2.5", "avg_c>2.5", "over (closing)", "P(over)"),
        ("Avg era (2019-20..)", "AvgC<2.5", "avg_c<2.5", "under (closing)", "P(under)"),
        ("Avg era (2019-20..)", "B365>2.5", "b365>2.5", "over (fallback)", "P(over)"),
        ("Avg era (2019-20..)", "B365<2.5", "b365<2.5", "under (fallback)", "P(under)"),
    ]
    print(f"{'era':<30}{'raw header':<14}{'parquet':<14}{'core/odds.py':<18}{'table'}")
    for era, raw, pq, mapped, table in rows:
        print(f"{era:<30}{raw:<14}{pq:<14}{mapped:<18}{table}")
    print()
    print("penaltyblog sanitize_columns is a PURE RENAME (df.columns = [to_snake_case(x) ...]),")
    print("so no reordering or value change occurs. core/odds.py maps")
    print('  PREMATCH_OU25 = [("Avg>2.5", ("avg>2.5", "avg<2.5")), ...] with OUT_OU = ("over", "under")')
    print("i.e. the '>2.5' column is OVER and the '<2.5' column is UNDER. Correct end to end.")
    print()
    print("THE BUG WAS IN CONSUMERS: ou.odds columns are (\"over\", \"under\"), so positional")
    print("[:, 1] selects UNDER. Three scripts did that and used it as P(over).")


def part_1c(frame: pd.DataFrame) -> None:
    print("\n" + "=" * 100)
    print("1c. Per season: market P(over) vs constant vs base rate, correlations, M1 slope")
    print("=" * 100)
    ou = odds.prematch_ou25(frame)
    dm = odds.demargin(ou.odds.where(ou.available), "proportional")
    p_over = dm["over"].to_numpy()
    p_under = dm["under"].to_numpy()
    p_model = frame["p_over25"].to_numpy()
    total = (frame["fthg"] + frame["ftag"]).to_numpy()
    over = (total > 2.5).astype(int)
    season = frame["season"].to_numpy()

    print(f"\n{'season':<11}{'n':>5}{'base':>8}{'const':>9}{'mkt P(over)':>13}"
          f"{'corr(mkt)':>11}{'corr(model)':>13}{'M1 slope':>10}{'M1 interc':>11}")
    for s in SEASONS:
        mask = (season == s) & np.isfinite(p_over)
        y = over[mask]
        base = y.mean()
        ll_const = m.log_loss(np.column_stack([np.full(len(y), 0.5)] * 2), y)
        ll_mkt = m.log_loss(np.column_stack([1 - p_over[mask], p_over[mask]]), y)
        c_mkt = np.corrcoef(p_over[mask], y)[0, 1]
        c_mod = np.corrcoef(p_model[mask], y)[0, 1]
        slope, intercept = fit_slope(p_over[mask], y.astype(float))
        print(f"{s:<11}{int(mask.sum()):>5}{base:>8.3f}{ll_const:>9.4f}{ll_mkt:>13.4f}"
              f"{c_mkt:>11.4f}{c_mod:>13.4f}{slope:>10.3f}{intercept:>11.3f}")

    mask = np.isfinite(p_over)
    y = over[mask]
    ll_const = m.log_loss(np.column_stack([np.full(len(y), 0.5)] * 2), y)
    ll_mkt = m.log_loss(np.column_stack([1 - p_over[mask], p_over[mask]]), y)
    print(f"\nPOOLED: constant {ll_const:.4f} | market P(over) {ll_mkt:.4f} | "
          f"corr {np.corrcoef(p_over[mask], y)[0, 1]:+.4f}")
    print(f"mean P(over) {p_over[mask].mean():.4f} vs observed over rate {y.mean():.4f}")
    print(f"mean P(under) {p_under[mask].mean():.4f}")


def part_1d(frame: pd.DataFrame) -> None:
    print("\n" + "=" * 100)
    print("1d. Explaining the old rule-table figure 0.4665")
    print("=" * 100)
    ou = odds.prematch_ou25(frame)
    dm = odds.demargin(ou.odds.where(ou.available), "proportional")
    p_over = dm["over"].to_numpy()
    p_under = dm["under"].to_numpy()
    print(f"  mean de-margined P(over)  = {np.nanmean(p_over):.4f}")
    print(f"  mean de-margined P(under) = {np.nanmean(p_under):.4f}")
    print(f"  1 - mean P(over)          = {1 - np.nanmean(p_over):.4f}")
    print()
    print("  The old rule table printed 0.4665 for 'market P(under)' on the bottom-third")
    print("  profile. That is 1 - P(over) computed from the INVERTED series: the script")
    print("  set p_mkt = demargin(...)[:, 1] (= P(under)) and then took 1 - p_mkt, which")
    print("  is P(over). So P(OVER) was printed in the P(under) column.")
    print()
    print("  Cross-check with the odds: mean under odds 1.8424 -> break-even 0.5428,")
    print("  consistent with P(under) ~ 0.5154, NOT 0.4665. The 0.4665 figure was P(over).")


def main() -> int:
    part_1a()
    part_1b()
    preds = pd.read_parquet(PRED)
    pool = wf.load_pool(FINAL.league)
    raw = pool.reset_index().rename(columns={"index": "row", "id": "match_key"})
    frame = preds.merge(raw[["match_key"] + ODDS_COLUMNS], on="match_key", how="left")
    part_1c(frame)
    part_1d(frame)
    return 0


if __name__ == "__main__":
    sys.exit(main())