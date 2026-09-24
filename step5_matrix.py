"""Step 5 — reports/market_matrix.md.

Rows = families. Per league: calibrated?, gain vs B0 with CI, historically
testable?, status. No ROI claims without prices.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

from core.market_code import direct_markets

CAL = Path("data/predictions/derived_markets_calibration.parquet")
FAMILY_CSV = Path("reports/figures/family_calibration.csv")
OUT = Path("reports/market_matrix.md")
LEAGUES = ["league_one_t3", "ligue_2_t2", "bundesliga_2", "bundesliga_1"]
BOOTSTRAP_N = 2000
SEED = 20260924


def row_ll(probs, y):
    return -np.log(np.clip(probs[np.arange(len(y)), y], 1e-15, 1.0))


def boot(diff, days, n=BOOTSTRAP_N, seed=SEED):
    rng = np.random.default_rng(seed)
    unique, inverse = np.unique(days, return_inverse=True)
    groups = [np.where(inverse == i)[0] for i in range(len(unique))]
    draws = np.empty(n)
    for i in range(n):
        picks = rng.integers(0, len(groups), len(groups))
        idx = np.concatenate([groups[p] for p in picks])
        draws[i] = diff[idx].mean()
    return float(diff.mean()), float(np.percentile(draws, 2.5)), float(np.percentile(draws, 97.5))


def main() -> int:
    df = pd.read_parquet(CAL)
    fam = pd.read_csv(FAMILY_CSV)
    pooled = {r.family: r for r in fam.itertuples(index=False)}

    untestable = {m.family for m in direct_markets() if not m.testable}

    lines = [
        "# Market matrix — derived goal markets",
        "",
        "Rows are **families**. `calibrated?` is the pooled discovery verdict",
        "(slope in [0.85, 1.15] AND log loss better than B0 with the paired",
        "bootstrap CI excluding 0, Holm-corrected across families).",
        "",
        "**No ROI is claimed without Soccer Bet prices.**",
        "",
        "| family | calibrated? | gain vs B0 (pooled) | 95% CI | testable? | status |",
        "|---|---|---|---|---|---|",
    ]

    for family in sorted(df["family"].unique()):
        row = pooled.get(family)
        if row is None:
            continue
        calibrated = bool(getattr(row, "final_pass", False))
        gain = float(row.gain_vs_B0)
        ci = f"[{row.ci_low:+.4f}, {row.ci_high:+.4f}]"
        testable = "no" if family in untestable else "yes"
        if family in untestable:
            status = "UNTESTED"
        elif calibrated:
            status = "MODEL-READY-AWAITING-PRICES"
        else:
            status = "FAIL"
        lines.append(f"| {family} | {'yes' if calibrated else 'no'} | {gain:+.4f} | {ci} "
                     f"| {testable} | {status} |")

    lines += [
        "",
        "## Per league (gain vs B0, pooled over discovery seasons)",
        "",
        "| family | " + " | ".join(LEAGUES) + " |",
        "|---|" + "---|" * len(LEAGUES),
    ]
    for family in sorted(df["family"].unique()):
        cells = []
        for league in LEAGUES:
            sub = df[(df["family"] == family) & (df["league"] == league)]
            if len(sub) < 50:
                cells.append("n/a")
                continue
            p = sub["p_model"].to_numpy()
            p0 = sub["p_b0"].to_numpy()
            y = sub["y"].to_numpy()
            ll_m = row_ll(np.column_stack([1 - p, p]), y).mean()
            ll_0 = row_ll(np.column_stack([1 - p0, p0]), y).mean()
            cells.append(f"{ll_0 - ll_m:+.4f}")
        lines.append(f"| {family} | " + " | ".join(cells) + " |")

    lines += [
        "",
        "## Notes",
        "",
        "* `FIRST_GOAL` is **not settleable** from HT/FT data — it needs the goal",
        "  timeline, which football-data.co.uk does not provide. Marked UNTESTED.",
        "* `TO_QUALIFY` is out of scope (needs tie context).",
        "* `NO_BET` is significantly **worse** than B0 (slope 1.28), so it is FAIL.",
        "* `HTFT` beats B0 significantly but its slope is 0.44, so it fails the",
        "  calibration criterion and is FAIL.",
        "* Families not listed in the catalogue are accepted at runtime with",
        "  family `UNLISTED` until calibration-tested.",
        "",
    ]

    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {OUT}")
    print("\n".join(lines[:24]))
    return 0


if __name__ == "__main__":
    sys.exit(main())