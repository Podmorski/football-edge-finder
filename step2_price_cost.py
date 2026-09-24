"""Step 2 — price-cost table (League One, descriptive).

Mean margin (sum of 1/odds - 1) per season for 1X2 and O/U 2.5 at three price
sources: market average (Avg/BbAv), B365 pre-match, Pinnacle pre-match.

Then repeats the payout check (1X2 + O/U 2.5, model-probability bins) at
Pinnacle pre-match prices, labelled "low-margin book sensitivity", and reports
bins clearing break-even per price source plus the bins-inspected count.

Margin is the cost of betting. Low-margin price sensitivity is descriptive,
not price-hunting.
"""

from __future__ import annotations

import sys

import numpy as np
import pandas as pd

from core import ledger, odds, walkforward as wf

SEASONS = ["2017-2018", "2018-2019", "2019-2020", "2020-2021", "2021-2022", "2022-2023"]
FINAL = wf.Config(xi=0.002, covid_mode="exclude_after", newcomer="newcomer_prior")
PRED = wf.PRED_DIR / f"{FINAL.config_id}.parquet"
BINS = 10

ODDS_COLUMNS = [
    "avg_h", "avg_d", "avg_a", "bb_av_h", "bb_av_d", "bb_av_a",
    "b365_h", "b365_d", "b365_a", "psh", "psd", "psa",
    "avg>2.5", "avg<2.5", "bb_av>2.5", "bb_av<2.5",
    "b365>2.5", "b365<2.5", "p>2.5", "p<2.5",
]


def wilson(k, n, z=1.96):
    if n == 0:
        return (float("nan"), float("nan"))
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (centre - half, centre + half)


def payout_bins(p_model, price, outcome, label, rows, bins_inspected):
    valid = np.isfinite(p_model) & np.isfinite(price) & (price > 1.0)
    edges = np.linspace(0, 1, BINS + 1)
    idx = np.clip(np.digitize(p_model, edges[1:-1]), 0, BINS - 1)
    clears = 0
    for b in range(BINS):
        mask = valid & (idx == b)
        n = int(mask.sum())
        if n == 0:
            continue
        bins_inspected[0] += 1
        hits = int(outcome[mask].sum())
        ci = wilson(hits, n)
        mean_odds = float(price[mask].mean())
        be = float((1.0 / price[mask]).mean())
        ok = bool(ci[0] > be)
        clears += int(ok)
        rows.append({
            "source": label, "bin": f"{edges[b]:.1f}-{edges[b+1]:.1f}", "n": n,
            "hit_rate": hits / n, "ci_low": ci[0], "ci_high": ci[1],
            "mean_odds": mean_odds, "break_even": be, "clears": ok,
        })
    return clears


def main() -> int:
    preds = pd.read_parquet(PRED)
    pool = wf.load_pool(FINAL.league)
    raw = pool.reset_index().rename(columns={"index": "row", "id": "match_key"})
    frame = preds.merge(raw[["match_key"] + ODDS_COLUMNS], on="match_key", how="left")

    fthg, ftag = frame["fthg"].to_numpy(), frame["ftag"].to_numpy()
    total = fthg + ftag
    season = frame["season"].to_numpy()

    print("=" * 100)
    print("Step 2 — price-cost table (League One, descriptive)")
    print("=" * 100)

    sources = {
        "market avg": (odds.prematch_1x2(frame), odds.prematch_ou25(frame)),
        "B365": (odds.b365_1x2(frame), odds.b365_ou25(frame)),
        "Pinnacle pre": (odds.pinnacle_1x2(frame), odds.pinnacle_ou25(frame)),
    }

    print("\n--- mean margin (sum of 1/odds - 1) per season ---")
    print(f"{'season':<11}" + "".join(f"{n + ' 1X2':>15}{n + ' O/U':>14}" for n in sources))
    for s in SEASONS:
        mask = season == s
        cells = []
        for name, (m1, mou) in sources.items():
            a = m1.available.to_numpy() & mask
            b = mou.available.to_numpy() & mask
            m1x2 = odds.booksum_margin(m1.odds[a]).mean() if a.any() else float("nan")
            mou25 = odds.booksum_margin(mou.odds[b]).mean() if b.any() else float("nan")
            cells.append(f"{m1x2:>15.4f}{mou25:>14.4f}")
        print(f"{s:<11}" + "".join(cells))

    print("\n--- coverage per source ---")
    for name, (m1, mou) in sources.items():
        print(f"  {name:<14} 1X2 {int(m1.available.sum()):>5}/{len(frame)}  "
              f"O/U {int(mou.available.sum()):>5}/{len(frame)}  "
              f"sources {sorted(set(m1.source.dropna()))}")

    # ---- payout check at each price source, model-probability bins ----
    print("\n--- payout check, model-probability bins, per price source ---")
    rows: list[dict] = []
    bins_inspected = [0]
    summary = []
    for name, (m1, mou) in sources.items():
        p1 = odds.demargin(m1.odds.where(m1.available), "proportional")
        pou = odds.demargin(mou.odds.where(mou.available), "proportional")
        c = 0
        c += payout_bins(frame["p_home"].to_numpy(), m1.odds["home"].to_numpy(dtype=float),
                         (fthg > ftag).astype(float), f"{name} 1X2 home", rows, bins_inspected)
        c += payout_bins(frame["p_draw"].to_numpy(), m1.odds["draw"].to_numpy(dtype=float),
                         (fthg == ftag).astype(float), f"{name} 1X2 draw", rows, bins_inspected)
        c += payout_bins(frame["p_away"].to_numpy(), m1.odds["away"].to_numpy(dtype=float),
                         (fthg < ftag).astype(float), f"{name} 1X2 away", rows, bins_inspected)
        c += payout_bins(frame["p_over25"].to_numpy(), mou.odds["over"].to_numpy(dtype=float),
                         (total > 2.5).astype(float), f"{name} O/U over", rows, bins_inspected)
        c += payout_bins((1 - frame["p_over25"]).to_numpy(), mou.odds["under"].to_numpy(dtype=float),
                         (total < 2.5).astype(float), f"{name} O/U under", rows, bins_inspected)
        summary.append((name, c))
        print(f"  {name:<14} bins clearing break-even: {c}")

    table = pd.DataFrame(rows)
    print(f"\nTOTAL BINS INSPECTED: {bins_inspected[0]} "
          f"(3 sources x 5 selections x up to {BINS} bins)")
    print("That is the multiple-testing count. No bin here is a validated rule.")
    print("\nbins clearing break-even by source:")
    for name, c in summary:
        print(f"  {name:<14} {c}")
    if len(table[table["clears"]]):
        print("\nclearing bins:")
        print(table[table["clears"]].to_string(index=False, float_format=lambda v: f"{v:.4f}"))
    else:
        print("\nno bin clears break-even at any price source")

    table.to_csv("reports/figures/price_cost_payout.csv", index=False)
    ledger.log_evaluation(
        league=FINAL.league, market="1X2+OU2.5", selection="price-cost",
        rule_config=f"PRICE COST {FINAL.config_id}",
        split="discovery:pooled", n_predictions=len(frame),
        log_loss="", brier="", benchmark_name="market_avg/B365/Pinnacle",
        benchmark_log_loss="", n_bets="", roi="", mean_clv="",
        notes=(f"bins inspected {bins_inspected[0]}; clearing per source "
               + "; ".join(f"{n}={c}" for n, c in summary)),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())