"""Step 3 — pre-register, then walk-forward calibration of the derived markets.

PRE-REGISTRATION (written before any number is computed, see
``research/preregistration.md`` and the ledger):

  Per family, success = pooled 2017-18..2022-23 (per league and pooled across the
  four leagues): calibration slope in [0.85, 1.15] AND log loss better than B0
  with a paired bootstrap 95% CI (2000 resamples, by matchday) excluding 0.
  Holm correction across families; raw and corrected reported.

Discovery seasons only. Confirmation is never touched.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import yaml
from scipy.optimize import minimize

from core import ledger, odds, walkforward as wf
from core.half_model import (
    MAX_HALF_GOALS,
    Anchor,
    batch_market_probs,
    fit_half_params,
    grids_to_flat,
    joint_grid,
    market_masks,
    solve_anchor,
)
from core.market_code import VOID, WIN, direct_markets, parse

SEASONS = ["2017-2018", "2018-2019", "2019-2020", "2020-2021", "2021-2022", "2022-2023"]
TARGETS = ["2018-2019", "2019-2020", "2020-2021", "2021-2022", "2022-2023"]
LEAGUES = ["league_one_t3", "ligue_2_t2", "bundesliga_2", "bundesliga_1"]
MAX_HALF = 6  # calibration grid truncation (P(>=7 goals in a half) is negligible)

BOOTSTRAP_N = 2000
SEED = 20260924

ODDS_COLUMNS = [
    "avg_h", "avg_d", "avg_a", "bb_av_h", "bb_av_d", "bb_av_a",
    "avg>2.5", "avg<2.5", "bb_av>2.5", "bb_av<2.5",
]

DIRECT_FAMILIES = {
    "WIN_BOTH_HALVES", "WIN_TO_NIL", "MARGIN", "NO_BET",
    "MORE_GOALS_HALF", "FIRST_GOAL", "TO_QUALIFY",
}

PREREG = Path("research/preregistration.md")


def logit(p):
    p = np.clip(np.asarray(p, dtype=float), 1e-6, 1 - 1e-6)
    return np.log(p / (1 - p))


def row_ll(probs, y):
    return -np.log(np.clip(probs[np.arange(len(y)), y], 1e-15, 1.0))


def fit_slope(p, y):
    design = np.column_stack([np.ones(len(p)), logit(p)])

    def objective(beta):
        z = design @ beta
        return float(np.mean(np.logaddexp(0.0, z) - y * z))

    beta = minimize(objective, x0=np.array([0.0, 1.0]), method="Nelder-Mead",
                    options={"xatol": 1e-8, "fatol": 1e-12, "maxiter": 4000}).x
    return float(beta[1]), float(beta[0])


def boot(diff, days, n=BOOTSTRAP_N, seed=SEED):
    """Paired bootstrap of mean(diff), resampling by matchday.

    Returns (mean, ci_low, ci_high, p_one_sided) where p is the fraction of
    resamples in which the model is NOT better (diff >= 0).
    """
    rng = np.random.default_rng(seed)
    unique, inverse = np.unique(days, return_inverse=True)
    groups = [np.where(inverse == i)[0] for i in range(len(unique))]
    draws = np.empty(n)
    for i in range(n):
        picks = rng.integers(0, len(groups), len(groups))
        idx = np.concatenate([groups[p] for p in picks])
        draws[i] = diff[idx].mean()
    p = float(np.mean(draws >= 0.0))
    return float(diff.mean()), float(np.percentile(draws, 2.5)), float(np.percentile(draws, 97.5)), p


def load_markets() -> list:
    catalogue = yaml.safe_load(Path("config/markets_catalogue.yaml").read_text(encoding="utf-8"))["markets"]
    direct = {m.code: m for m in direct_markets()}
    out = []
    for entry in catalogue:
        if entry["family"] in DIRECT_FAMILIES:
            out.append(direct[entry["code"]])
        else:
            out.append(parse(entry["code"], entry["family"]))
    return out


def preregister() -> None:
    text = """# Pre-registration — derived goal markets (Phase 3)

Written **before** any calibration number was computed (2026-09-24).

## Hypothesis
Soccer Bet prices hundreds of derived goal markets by formula. A joint
half-by-half model anchored on the sharp **pre-match** 1X2 + O/U 2.5 should
price some families more accurately than a plausible book formula (B0: 50/50
half split, independent halves).

## Success criterion (per family)
Pooled over discovery seasons 2017-18..2022-23 (per league and pooled across the
four leagues):

1. calibration slope in **[0.85, 1.15]**, AND
2. log loss better than **B0** with a paired bootstrap 95% CI
   (2000 resamples, by matchday) **excluding 0**.

Holm correction across families; raw and corrected p-values both reported.

## What this does NOT claim
No ROI, no staking, no edge. A family that passes is a **CONFIRMATION
CANDIDATE** only. Confirmation seasons (2023-24+) are untouched.
"""
    PREREG.parent.mkdir(parents=True, exist_ok=True)
    PREREG.write_text(text, encoding="utf-8")
    ledger.append_note(
        "PRE-REGISTRATION (Phase 3 derived markets): per family, success = pooled "
        "2017-18..2022-23 calibration slope in [0.85,1.15] AND log loss better than B0 "
        "with paired bootstrap 95% CI (2000, by matchday) excluding 0; Holm correction "
        "across families. Written before computing."
    )
    print(f"pre-registered -> {PREREG}")


def league_frame(slug: str) -> pd.DataFrame:
    pool = wf.load_pool(slug)
    raw = pool.reset_index().rename(columns={"index": "row", "id": "match_key"})
    frame = raw[["match_key", "date", "season", "team_home", "team_away",
                 "fthg", "ftag", "hthg", "htag"] + ODDS_COLUMNS].copy()
    prem = odds.prematch_1x2(frame)
    ou = odds.prematch_ou25(frame)
    p1 = odds.demargin(prem.odds.where(prem.available), "proportional")
    pou = odds.demargin(ou.odds.where(ou.available), "proportional")
    frame["p_home"] = p1["home"].to_numpy()
    frame["p_draw"] = p1["draw"].to_numpy()
    frame["p_away"] = p1["away"].to_numpy()
    frame["p_over25"] = pou["over"].to_numpy()
    # half-time scores are required for every derived market
    frame = frame.dropna(subset=["hthg", "htag"])
    return frame.dropna(subset=["p_home", "p_draw", "p_away", "p_over25"]).reset_index(drop=True)


def main() -> int:
    preregister()
    markets = load_markets()
    masks = market_masks(markets, max_half=MAX_HALF)
    print(f"markets: {len(markets)} | masks built")

    records: list[dict] = []
    split_report: list[dict] = []
    anchor_residuals: list[float] = []

    for slug in LEAGUES:
        frame = league_frame(slug)
        t0 = time.perf_counter()
        anchors = []
        for r in frame.itertuples(index=False):
            a = solve_anchor(r.p_home, r.p_draw, r.p_away, r.p_over25)
            anchors.append(a)
            anchor_residuals.append(a.residual)
        frame = frame.assign(lam=[a.lam for a in anchors], mu=[a.mu for a in anchors])
        print(f"\n{slug}: {len(frame)} matches, anchors in {time.perf_counter()-t0:.0f}s")

        for target in TARGETS:
            train = frame[frame["season"] < target]
            test = frame[frame["season"] == target]
            if len(train) < 200 or test.empty:
                continue
            rows = [{"lam": r.lam, "mu": r.mu, "hth": r.hthg, "hta": r.htag,
                     "fth": r.fthg, "fta": r.ftag} for r in train.itertuples(index=False)]
            params = fit_half_params(rows)
            split_report.append({
                "league": slug, "target": target, "split_a": params.split_a,
                "split_b": params.split_b, "split_c": params.split_c,
                "share_at_2.6": params.first_half_share(1.4, 1.2),
                "mult_home_lead": params.state_mult.get(("home", "home_lead"), 1.0),
                "mult_home_level": params.state_mult.get(("home", "level"), 1.0),
                "mult_home_trail": params.state_mult.get(("home", "away_lead"), 1.0),
                "mult_away_lead": params.state_mult.get(("away", "away_lead"), 1.0),
                "mult_away_level": params.state_mult.get(("away", "level"), 1.0),
                "mult_away_trail": params.state_mult.get(("away", "home_lead"), 1.0),
            })

            grids_model, grids_b0, grids_b1 = [], [], []
            for r in test.itertuples(index=False):
                anchor = Anchor(lam=r.lam, mu=r.mu, residual=0.0)
                grids_model.append(joint_grid(anchor, params, MAX_HALF))
                grids_b0.append(joint_grid(anchor, None, MAX_HALF, fixed_share=0.5, use_state=False))
                grids_b1.append(joint_grid(anchor, None, MAX_HALF, fixed_share=0.45, use_state=False))

            probs_model = batch_market_probs(grids_to_flat(grids_model), masks)
            probs_b0 = batch_market_probs(grids_to_flat(grids_b0), masks)
            probs_b1 = batch_market_probs(grids_to_flat(grids_b1), masks)

            # Record EVERY (market, match) pair: y = 1 if the market wins, 0 if it
            # loses. Void outcomes are excluded (stake returned, no binary label).
            for i, r in enumerate(test.itertuples(index=False)):
                for market in markets:
                    outcome = market.outcome(int(r.hthg), int(r.htag), int(r.fthg), int(r.ftag))
                    if outcome == VOID:
                        continue
                    records.append({
                        "league": slug, "season": target, "date": r.date,
                        "family": market.family, "code": market.code,
                        "p_model": float(probs_model[market.code][0][i]),
                        "p_b0": float(probs_b0[market.code][0][i]),
                        "p_b1": float(probs_b1[market.code][0][i]),
                        "y": 1 if outcome == WIN else 0,
                    })
        print(f"  records so far: {len(records)}")

    df = pd.DataFrame(records)
    df.to_parquet("data/predictions/derived_markets_calibration.parquet", index=False)
    print(f"\ntotal (market, match) win-records: {len(df)}")

    # ---------------- per-family calibration ----------------
    print("\n" + "=" * 100)
    print("PER-FAMILY CALIBRATION (pooled discovery, all four leagues)")
    print("=" * 100)
    print(f"{'family':<22}{'n':>8}{'slope':>8}{'intercept':>10}{'ll_model':>10}"
          f"{'ll_B0':>9}{'ll_B1':>9}{'gain_vs_B0':>12}{'95% CI':>22}")
    fam_rows = []
    for family, sub in df.groupby("family"):
        p = sub["p_model"].to_numpy()
        y = sub["y"].to_numpy()
        slope, intercept = fit_slope(p, y)
        ll_m = row_ll(np.column_stack([1 - p, p]), y).mean()
        ll0 = row_ll(np.column_stack([1 - sub["p_b0"].to_numpy(), sub["p_b0"].to_numpy()]), y).mean()
        ll1 = row_ll(np.column_stack([1 - sub["p_b1"].to_numpy(), sub["p_b1"].to_numpy()]), y).mean()
        diff = row_ll(np.column_stack([1 - p, p]), y) - row_ll(
            np.column_stack([1 - sub["p_b0"].to_numpy(), sub["p_b0"].to_numpy()]), y)
        d = boot(diff, sub["date"].to_numpy())
        fam_rows.append({"family": family, "n": len(sub), "slope": slope, "intercept": intercept,
                         "ll_model": ll_m, "ll_B0": ll0, "ll_B1": ll1,
                         "gain_vs_B0": ll0 - ll_m, "ci_low": d[1], "ci_high": d[2],
                         "p_one_sided": d[3]})
        print(f"{family:<22}{len(sub):>8}{slope:>8.3f}{intercept:>10.3f}{ll_m:>10.4f}"
              f"{ll0:>9.4f}{ll1:>9.4f}{ll0 - ll_m:>12.4f}"
              f"{f'[{d[1]:+.4f}, {d[2]:+.4f}]':>22}")

    fam = pd.DataFrame(fam_rows).sort_values("gain_vs_B0", ascending=False)

    # Holm correction across families. The CI is on the DIFFERENCE
    # (model - B0), so "beats B0" means the diff is negative and its CI is
    # entirely below zero.
    fam["passes_slope"] = fam["slope"].between(0.85, 1.15)
    fam["beats_b0"] = (fam["gain_vs_B0"] > 0) & (fam["ci_high"] < 0)
    fam["raw_pass"] = fam["passes_slope"] & fam["beats_b0"]

    print("\nHolm correction across families (raw vs corrected):")
    m = len(fam)
    ordered = fam.sort_values("p_one_sided").index
    holm_pass = {}
    for rank, idx in enumerate(ordered):
        alpha = 0.05 / (m - rank)
        row = fam.loc[idx]
        holm_pass[idx] = bool(row["p_one_sided"] < alpha)
        print(f"  {row['family']:<22} p={row['p_one_sided']:.4f} holm_alpha={alpha:.4f} "
              f"slope={row['slope']:.3f} gain={row['gain_vs_B0']:+.4f} "
              f"raw_pass={bool(row['raw_pass'])} holm_pass={holm_pass[idx]}")
    fam["holm_pass"] = fam.index.map(holm_pass)
    fam["final_pass"] = fam["raw_pass"] & fam["holm_pass"]
    print(f"\nfamilies passing raw : {int(fam['raw_pass'].sum())} of {m}")
    print(f"families passing Holm: {int(fam['final_pass'].sum())} of {m}")
    if int(fam["final_pass"].sum()):
        print("PASSING FAMILIES:")
        for r in fam[fam["final_pass"]].itertuples(index=False):
            print(f"  {r.family:<22} slope {r.slope:.3f} gain {r.gain_vs_B0:+.4f} "
                  f"CI [{r.ci_low:+.4f}, {r.ci_high:+.4f}] p={r.p_one_sided:.4f}")

    pd.DataFrame(split_report).to_csv("reports/figures/half_split_params.csv", index=False)
    fam.to_csv("reports/figures/family_calibration.csv", index=False)
    print(f"\nanchor residual: mean {np.mean(anchor_residuals):.5f} "
          f"p50 {np.percentile(anchor_residuals,50):.5f} "
          f"p95 {np.percentile(anchor_residuals,95):.5f} max {np.max(anchor_residuals):.5f}")

    # ---------------- headline tables ----------------
    print("\n" + "=" * 100)
    print("HEADLINE (a): P(I>II), P(I=II), P(I<II) — model vs B0 vs observed")
    print("=" * 100)
    for code in ("I>II", "I=II", "I<II"):
        sub = df[df["code"] == code]
        if sub.empty:
            continue
        print(f"  {code:<6} n={len(sub):<7} model {sub['p_model'].mean():.4f} | "
              f"B0 {sub['p_b0'].mean():.4f} | observed {sub['y'].mean():.4f}")

    print("\n" + "=" * 100)
    print("HEADLINE (b): RESULT_AND_GOALS and HTFT_AND_GOALS per code")
    print("=" * 100)
    print(f"  {'code':<14}{'n':>7}{'model':>9}{'B0':>9}{'observed':>10}{'model-B0':>10}")
    for family in ("RESULT_AND_GOALS", "HTFT_AND_GOALS"):
        for code, sub in df[df["family"] == family].groupby("code"):
            print(f"  {code:<14}{len(sub):>7}{sub['p_model'].mean():>9.4f}"
                  f"{sub['p_b0'].mean():>9.4f}{sub['y'].mean():>10.4f}"
                  f"{sub['p_model'].mean() - sub['p_b0'].mean():>10.4f}")

    # ---------------- long-shot check ----------------
    print("\n" + "=" * 100)
    print("LONG-SHOT CHECK: markets with model p < 0.10")
    print("=" * 100)
    ls = df[df["p_model"] < 0.10]
    if len(ls):
        print(f"  n={len(ls)}  model mean {ls['p_model'].mean():.4f} | "
              f"observed {ls['y'].mean():.4f}")
        for family, sub in ls.groupby("family"):
            print(f"    {family:<22} n={len(sub):<7} model {sub['p_model'].mean():.4f} "
                  f"observed {sub['y'].mean():.4f}")
    else:
        print("  none")

    ledger.log_evaluation(
        league="ALL", market="derived", selection="families",
        rule_config="PHASE3 CALIBRATION", split="discovery:walk-forward",
        n_predictions=len(df), log_loss=float(fam["ll_model"].mean()), brier="",
        benchmark_name="B0", benchmark_log_loss=float(fam["ll_B0"].mean()),
        n_bets="", roi="", mean_clv="",
        notes=(f"families={len(fam)}; raw_pass={int(fam['raw_pass'].sum())}; "
               f"best={fam.iloc[0]['family']} gain {fam.iloc[0]['gain_vs_B0']:+.4f}"),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())