"""Step 3 — combo menu + calibration (no odds needed).

Reads the final config's predictions (which carry every market as a grid-cell
sum), writes the market matrix, and reports per market:
  * 10-bin reliability (count, observed rate, 95% CI)
  * log loss vs the naive base rate
  * calibration slope / intercept (logistic of outcome on logit(p))
  * ECE, used to rank markets by calibration
  * over-confident high-probability bins (mean predicted >= 0.6)
"""

from __future__ import annotations

import sys

import numpy as np
import pandas as pd
from scipy.optimize import minimize

from core import ledger, walkforward as wf
from models import league_one_dixon_coles as m

SEASONS = ["2017-2018", "2018-2019", "2019-2020", "2020-2021", "2021-2022", "2022-2023"]
FINAL = wf.Config(xi=0.002, covid_mode="exclude_after", newcomer="newcomer_prior")
PRED = wf.PRED_DIR / f"{FINAL.config_id}.parquet"
MARKETS_PATH = wf.PRED_DIR / f"{FINAL.config_id}_markets.parquet"

# market column -> (label, outcome function of (fthg, ftag))
MARKETS = {
    "p_home": ("1X2 home", lambda h, a: h > a),
    "p_draw": ("1X2 draw", lambda h, a: h == a),
    "p_away": ("1X2 away", lambda h, a: h < a),
    "p_dc_1x": ("DC 1X", lambda h, a: h >= a),
    "p_dc_12": ("DC 12", lambda h, a: h != a),
    "p_dc_x2": ("DC X2", lambda h, a: h <= a),
    "p_over15": ("Over 1.5", lambda h, a: h + a >= 2),
    "p_under15": ("Under 1.5", lambda h, a: h + a < 2),
    "p_over25": ("Over 2.5", lambda h, a: h + a >= 3),
    "p_under25": ("Under 2.5", lambda h, a: h + a < 3),
    "p_over35": ("Over 3.5", lambda h, a: h + a >= 4),
    "p_under35": ("Under 3.5", lambda h, a: h + a < 4),
    "p_btts": ("BTTS yes", lambda h, a: (h >= 1) & (a >= 1)),
    "p_btts_no": ("BTTS no", lambda h, a: ~((h >= 1) & (a >= 1))),
    "p_under25_btts_no": ("Under 2.5 & BTTS no", lambda h, a: (h + a < 3) & ~((h >= 1) & (a >= 1))),
    "p_over25_btts_yes": ("Over 2.5 & BTTS yes", lambda h, a: (h + a >= 3) & (h >= 1) & (a >= 1)),
    "p_home_under35": ("Home & Under 3.5", lambda h, a: (h > a) & (h + a < 4)),
    "p_away_under35": ("Away & Under 3.5", lambda h, a: (h < a) & (h + a < 4)),
    "p_home_btts_no": ("Home & BTTS no", lambda h, a: (h > a) & ~((h >= 1) & (a >= 1))),
    "p_draw_under25": ("Draw & Under 2.5", lambda h, a: (h == a) & (h + a < 3)),
    "p_home_or_draw_under25": ("Home or Draw & Under 2.5", lambda h, a: (h >= a) & (h + a < 3)),
    "p_home_over15": ("Home & Over 1.5", lambda h, a: (h > a) & (h + a >= 2)),
}

BINS = 10


def wilson(k, n, z=1.96):
    if n == 0:
        return (float("nan"), float("nan"))
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (centre - half, centre + half)


def logit(p):
    p = np.clip(np.asarray(p, dtype=float), 1e-6, 1 - 1e-6)
    return np.log(p / (1 - p))


def calibration_fit(p, y):
    """Logistic regression of the outcome on logit(p): slope and intercept."""
    design = np.column_stack([np.ones(len(p)), logit(p)])

    def objective(beta):
        z = design @ beta
        return float(np.mean(np.logaddexp(0.0, z) - y * z))

    beta = minimize(objective, x0=np.array([0.0, 1.0]), method="Nelder-Mead",
                    options={"xatol": 1e-8, "fatol": 1e-12, "maxiter": 4000}).x
    return float(beta[1]), float(beta[0])


def main() -> int:
    frame = pd.read_parquet(PRED)
    frame.to_parquet(MARKETS_PATH)
    print("=" * 100)
    print("Step 3 — combo menu + calibration")
    print("=" * 100)
    print(f"rows {len(frame)} | markets {len(MARKETS)} | written to {MARKETS_PATH.name}")

    fthg = frame["fthg"].to_numpy()
    ftag = frame["ftag"].to_numpy()

    rows = []
    for column, (label, fn) in MARKETS.items():
        p = frame[column].to_numpy(dtype=float)
        y = np.asarray(fn(fthg, ftag)).astype(float)
        base = float(y.mean())
        ll = m.log_loss(np.column_stack([1 - p, p]), y.astype(int))
        ll_naive = m.log_loss(
            np.column_stack([np.full(len(y), 1 - base), np.full(len(y), base)]), y.astype(int)
        )
        slope, intercept = calibration_fit(p, y)

        edges = np.linspace(0, 1, BINS + 1)
        idx = np.clip(np.digitize(p, edges[1:-1]), 0, BINS - 1)
        ece, overconf = 0.0, []
        for b in range(BINS):
            mask = idx == b
            if mask.sum() == 0:
                continue
            pred = float(p[mask].mean())
            obs = float(y[mask].mean())
            ece += (mask.sum() / len(p)) * abs(pred - obs)
            if pred >= 0.6 and obs < pred:
                overconf.append((f"{edges[b]:.1f}-{edges[b+1]:.1f}", int(mask.sum()), pred, obs))

        rows.append({
            "market": column, "label": label, "n": len(p), "base_rate": base,
            "mean_pred": float(p.mean()), "log_loss": ll, "naive_log_loss": ll_naive,
            "ll_gain_vs_naive": ll_naive - ll, "slope": slope, "intercept": intercept,
            "ece": ece, "overconfident_bins": len(overconf),
        })

    table = pd.DataFrame(rows).sort_values("ece").reset_index(drop=True)
    print("\n--- markets ranked by calibration (ECE, best first) ---")
    print(f"{'market':<24}{'n':>5}{'base':>8}{'mean_p':>8}{'logloss':>9}{'naive':>8}"
          f"{'gain':>8}{'slope':>8}{'interc':>8}{'ECE':>8}{'overconf':>9}")
    for r in table.itertuples(index=False):
        print(f"{r.label:<24}{r.n:>5}{r.base_rate:>8.3f}{r.mean_pred:>8.3f}"
              f"{r.log_loss:>9.4f}{r.naive_log_loss:>8.4f}{r.ll_gain_vs_naive:>8.4f}"
              f"{r.slope:>8.3f}{r.intercept:>8.3f}{r.ece:>8.4f}{r.overconfident_bins:>9}")

    print("\n--- over-confident high-probability bins (mean predicted >= 0.6) ---")
    any_flag = False
    for column, (label, fn) in MARKETS.items():
        p = frame[column].to_numpy(dtype=float)
        y = np.asarray(fn(fthg, ftag)).astype(float)
        edges = np.linspace(0, 1, BINS + 1)
        idx = np.clip(np.digitize(p, edges[1:-1]), 0, BINS - 1)
        for b in range(BINS):
            mask = idx == b
            if mask.sum() == 0:
                continue
            pred, obs = float(p[mask].mean()), float(y[mask].mean())
            if pred >= 0.6 and obs < pred:
                ci = wilson(int(y[mask].sum()), int(mask.sum()))
                print(f"  {label:<24} bin {edges[b]:.1f}-{edges[b+1]:.1f} n={int(mask.sum()):<4} "
                      f"pred {pred:.3f} obs {obs:.3f} CI [{ci[0]:.3f}, {ci[1]:.3f}]")
                any_flag = True
    if not any_flag:
        print("  none")

    print("\n--- best and worst calibrated ---")
    print(f"  best : {table.iloc[0]['label']} (ECE {table.iloc[0]['ece']:.4f})")
    print(f"  worst: {table.iloc[-1]['label']} (ECE {table.iloc[-1]['ece']:.4f})")

    table.to_csv("reports/figures/combo_calibration.csv", index=False)
    ledger.log_evaluation(
        league=FINAL.league, market="combo-menu", selection="all",
        rule_config=f"COMBO CALIBRATION {FINAL.config_id}",
        split="discovery:pooled", n_predictions=len(frame),
        log_loss=float(table["log_loss"].mean()), brier="",
        benchmark_name="naive_base_rate",
        benchmark_log_loss=float(table["naive_log_loss"].mean()),
        n_bets="", roi="", mean_clv="",
        notes=(f"markets={len(table)}; best ECE {table.iloc[0]['ece']:.4f} "
               f"({table.iloc[0]['label']}); worst {table.iloc[-1]['ece']:.4f} "
               f"({table.iloc[-1]['label']})"),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())