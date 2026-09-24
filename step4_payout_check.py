"""Step 4 — payout check (1X2 + O/U 2.5, market-average pre-match odds).

Descriptive only: no staking, no ROI optimisation, no rule tuning.

For each selection (home, draw, away, over, under), bin by
  (i) the model probability, and
  (ii) the market implied probability,
and report per bin: n, observed hit rate (95% CI), mean odds,
break-even = mean(1/odds) (raw, no de-margining), and whether the hit-rate CI
sits above break-even.

Every table is logged to the ledger, and the total number of bins inspected is
stated so the multiple-testing count is explicit.
"""

from __future__ import annotations

import sys

import numpy as np
import pandas as pd

from core import ledger, odds, walkforward as wf
from models import league_one_dixon_coles as m

SEASONS = ["2017-2018", "2018-2019", "2019-2020", "2020-2021", "2021-2022", "2022-2023"]
FINAL = wf.Config(xi=0.002, covid_mode="exclude_after", newcomer="newcomer_prior")
PRED = wf.PRED_DIR / f"{FINAL.config_id}.parquet"

BINS = 10
ODDS_COLUMNS = [
    "avg_h", "avg_d", "avg_a", "bb_av_h", "bb_av_d", "bb_av_a",
    "b365_h", "b365_d", "b365_a", "avg>2.5", "avg<2.5", "bb_av>2.5", "bb_av<2.5",
    "b365>2.5", "b365<2.5",
]


def wilson(k, n, z=1.96):
    if n == 0:
        return (float("nan"), float("nan"))
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (centre - half, centre + half)


def main() -> int:
    preds = pd.read_parquet(PRED)
    pool = wf.load_pool(FINAL.league)
    raw = pool.reset_index().rename(columns={"index": "row", "id": "match_key"})
    frame = preds.merge(raw[["match_key"] + ODDS_COLUMNS], on="match_key", how="left")

    fthg = frame["fthg"].to_numpy()
    ftag = frame["ftag"].to_numpy()
    total = fthg + ftag

    prem = odds.prematch_1x2(frame)
    ou = odds.prematch_ou25(frame)
    p_mkt_1x2 = odds.demargin(prem.odds.where(prem.available), "proportional")
    p_mkt_ou = odds.demargin(ou.odds.where(ou.available), "proportional")

    print("=" * 104)
    print("Step 4 — payout check (descriptive only)")
    print("=" * 104)
    print(f"1X2 price source(s): {sorted(set(prem.source.dropna()))} "
          f"({int(prem.available.sum())}/{len(frame)})")
    print(f"O/U price source(s): {sorted(set(ou.source.dropna()))} "
          f"({int(ou.available.sum())}/{len(frame)})")

    selections = [
        ("home", frame["p_home"].to_numpy(), p_mkt_1x2["home"].to_numpy(),
         prem.odds["home"].to_numpy(dtype=float), (fthg > ftag).astype(float)),
        ("draw", frame["p_draw"].to_numpy(), p_mkt_1x2["draw"].to_numpy(),
         prem.odds["draw"].to_numpy(dtype=float), (fthg == ftag).astype(float)),
        ("away", frame["p_away"].to_numpy(), p_mkt_1x2["away"].to_numpy(),
         prem.odds["away"].to_numpy(dtype=float), (fthg < ftag).astype(float)),
        ("over", frame["p_over25"].to_numpy(), p_mkt_ou["over"].to_numpy(),
         ou.odds["over"].to_numpy(dtype=float), (total > 2.5).astype(float)),
        ("under", (1 - frame["p_over25"]).to_numpy(), p_mkt_ou["under"].to_numpy(),
         ou.odds["under"].to_numpy(dtype=float), (total < 2.5).astype(float)),
    ]

    bins_inspected = 0
    rows = []
    for name, p_model, p_market, price, outcome in selections:
        for scheme, p_bin in (("model", p_model), ("market", p_market)):
            valid = np.isfinite(p_bin) & np.isfinite(price) & (price > 1.0)
            edges = np.linspace(0, 1, BINS + 1)
            idx = np.clip(np.digitize(p_bin, edges[1:-1]), 0, BINS - 1)
            print(f"\n--- {name.upper()} binned by {scheme} probability ---")
            print(f"  {'bin':<12}{'n':>5}{'hit':>8}{'95% CI':>20}{'mean odds':>11}"
                  f"{'break-even':>12}{'CI>BE':>8}")
            for b in range(BINS):
                mask = valid & (idx == b)
                n = int(mask.sum())
                if n == 0:
                    continue
                bins_inspected += 1
                hits = int(outcome[mask].sum())
                hit = hits / n
                ci = wilson(hits, n)
                mean_odds = float(price[mask].mean())
                be = float((1.0 / price[mask]).mean())
                clears = bool(ci[0] > be)
                print(f"  {f'{edges[b]:.1f}-{edges[b+1]:.1f}':<12}{n:>5}{hit:>8.3f}"
                      f"{f'[{ci[0]:.3f}, {ci[1]:.3f}]':>20}{mean_odds:>11.3f}"
                      f"{be:>12.4f}{str(clears):>8}")
                rows.append({
                    "selection": name, "scheme": scheme,
                    "bin": f"{edges[b]:.1f}-{edges[b+1]:.1f}", "n": n,
                    "hit_rate": hit, "ci_low": ci[0], "ci_high": ci[1],
                    "mean_odds": mean_odds, "break_even": be, "ci_above_break_even": clears,
                })

    table = pd.DataFrame(rows)
    print("\n" + "=" * 104)
    print(f"TOTAL BINS INSPECTED: {bins_inspected}  "
          f"(5 selections x 2 binning schemes x up to {BINS} bins)")
    print("This is the multiple-testing count: with this many bins, some will clear")
    print("break-even by chance alone. No bin here is a validated rule.")
    clears = table[table["ci_above_break_even"]]
    print(f"\nbins whose hit-rate CI sits above break-even: {len(clears)}")
    if len(clears):
        print(clears.to_string(index=False, float_format=lambda v: f"{v:.4f}"))

    table.to_csv("reports/figures/payout_check.csv", index=False)
    for name, _, _, _, _ in selections:
        sub = table[table["selection"] == name]
        ledger.log_evaluation(
            league=FINAL.league, market="1X2+OU2.5", selection=name,
            rule_config=f"PAYOUT CHECK {FINAL.config_id}",
            split="discovery:pooled", n_predictions=int(sub["n"].sum()),
            log_loss="", brier="", benchmark_name="market_average_odds",
            benchmark_log_loss="", n_bets="", roi="", mean_clv="",
            notes=(f"bins={len(sub)}; above break-even={int(sub['ci_above_break_even'].sum())}; "
                   f"descriptive only, no staking"),
        )
    print(f"\nlogged {len(selections)} payout tables to the ledger")
    return 0


if __name__ == "__main__":
    sys.exit(main())