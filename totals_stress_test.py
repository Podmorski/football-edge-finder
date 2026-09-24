"""Step 1 — totals stress test.

Decomposes the O/U 2.5 blend so the model is credited only for what it adds
beyond a market recalibration, and probes whether any market bias is tied to
recent scoring (the over-reaction hypothesis).

Models, walk-forward by season (fit on earlier discovery seasons only):
  M0  market de-margined, as-is
  M1  logistic on logit(p_mkt) only          -> market recalibration
  M2  logistic on logit(p_mkt) + logit(p_model)
  Mprobe  M1 + each team's last-5 and last-10 total goals (home team home-only,
          away team away-only)

Credit the MODEL only for M2 - M1. Paired bootstrap 95% CIs, 2000 resamples,
resampled by matchday.
"""

from __future__ import annotations

import sys

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.stats import poisson

from core import ledger, odds, walkforward as wf
from models import league_one_dixon_coles as m

SEASONS = ["2017-2018", "2018-2019", "2019-2020", "2020-2021", "2021-2022", "2022-2023"]
TARGETS = ["2018-2019", "2019-2020", "2020-2021", "2021-2022", "2022-2023"]
FINAL = wf.Config(xi=0.002, covid_mode="exclude_after", newcomer="newcomer_prior")

BOOTSTRAP_N = 2000
SEED = 20260924

ODDS_COLUMNS = [
    "avg>2.5", "avg<2.5", "bb_av>2.5", "bb_av<2.5", "b365>2.5", "b365<2.5",
    "avg_c>2.5", "avg_c<2.5", "pc>2.5", "pc<2.5",
]


def logit(p: np.ndarray) -> np.ndarray:
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return np.log(p / (1 - p))


def row_ll(probs: np.ndarray, y: np.ndarray) -> np.ndarray:
    return -np.log(np.clip(probs[np.arange(len(y)), y], 1e-15, 1.0))


def fit_logistic(design: np.ndarray, y: np.ndarray) -> np.ndarray:
    def objective(beta):
        z = design @ beta
        return float(np.mean(np.logaddexp(0.0, z) - y * z))

    return minimize(objective, x0=np.zeros(design.shape[1]), method="Nelder-Mead",
                    options={"xatol": 1e-7, "fatol": 1e-11, "maxiter": 6000}).x


def predict_logistic(design: np.ndarray, beta: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-(design @ beta)))


def boot(diff: np.ndarray, days: np.ndarray, n: int = BOOTSTRAP_N, seed: int = SEED):
    rng = np.random.default_rng(seed)
    unique, inverse = np.unique(days, return_inverse=True)
    groups = [np.where(inverse == i)[0] for i in range(len(unique))]
    draws = np.empty(n)
    for i in range(n):
        picks = rng.integers(0, len(groups), len(groups))
        idx = np.concatenate([groups[p] for p in picks])
        draws[i] = diff[idx].mean()
    return float(diff.mean()), float(np.percentile(draws, 2.5)), float(np.percentile(draws, 97.5))


def implied_total_lambda(p_over: float) -> float:
    """Poisson mean whose P(X >= 3) equals the given over-2.5 probability."""
    lo, hi = 0.05, 12.0
    for _ in range(120):
        mid = 0.5 * (lo + hi)
        if poisson.sf(2, mid) > p_over:
            hi = mid
        else:
            lo = mid
    return 0.5 * (lo + hi)


def form_table(pool: pd.DataFrame, cutoff: pd.Timestamp) -> dict:
    """Leakage-free last-5 / last-10 total goals, home-only and away-only."""
    sub = pool[pool["date"] < cutoff].sort_values("date")
    out: dict = {}
    for venue, column in (("home", "team_home"), ("away", "team_away")):
        for n in (5, 10):
            tail = sub.groupby(column).tail(n)
            totals = (tail["fthg"] + tail["ftag"]).groupby(tail[column]).mean()
            out[(venue, n)] = totals.to_dict()
    return out


def main() -> int:
    pool = wf.load_pool(FINAL.league)
    preds = wf.run(FINAL, SEASONS, pool=pool)
    raw = pool.reset_index().rename(columns={"index": "row", "id": "match_key"})
    frame = preds.merge(raw[["match_key"] + ODDS_COLUMNS], on="match_key", how="left")

    ou = odds.prematch_ou25(frame)
    p_mkt = odds.demargin(ou.odds.where(ou.available), "proportional").to_numpy()[:, 1]
    p_mkt_pow = odds.demargin(ou.odds.where(ou.available), "power").to_numpy()[:, 1]
    raw_over = ou.odds["over"].to_numpy(dtype=float)
    p_model = frame["p_over25"].to_numpy()
    total = (frame["fthg"] + frame["ftag"]).to_numpy()
    over = (total > 2.5).astype(int)
    days = frame["date"].to_numpy()
    season = frame["season"].to_numpy()
    ok = np.isfinite(p_mkt) & np.isfinite(raw_over)

    print("=" * 96)
    print("Step 1 — totals stress test")
    print("=" * 96)
    print(f"rows with a pre-match O/U price: {int(ok.sum())}/{len(frame)}")

    # ---------------- per-season correlations ----------------
    print("\n--- per season: correlation with the actual over outcome ---")
    print(f"{'season':<11}{'n':>5}{'corr(mkt P(over))':>19}{'corr(model P(over))':>21}"
          f"{'mkt E[total]':>14}{'model E[total]':>16}{'actual E[total]':>16}")
    for s in SEASONS:
        idx = np.where((season == s) & ok)[0]
        if len(idx) == 0:
            continue
        c_mkt = np.corrcoef(p_mkt[idx], over[idx])[0, 1]
        c_mod = np.corrcoef(p_model[idx], over[idx])[0, 1]
        mkt_e = np.mean([implied_total_lambda(p) for p in p_mkt[idx]])
        mod_e = float((frame["expected_home_goals"].to_numpy()[idx]
                       + frame["expected_away_goals"].to_numpy()[idx]).mean())
        print(f"{s:<11}{len(idx):>5}{c_mkt:>19.4f}{c_mod:>21.4f}"
              f"{mkt_e:>14.3f}{mod_e:>16.3f}{total[idx].mean():>16.3f}")

    # ---------------- M0 / M1 / M2 decomposition ----------------
    print("\n--- walk-forward decomposition (credit the model only for M2 - M1) ---")
    print(f"{'target':<11}{'M0 mkt':>10}{'M1 recal':>10}{'M2 recal+model':>16}"
          f"{'M1-M0':>10}{'M2-M1':>10}")

    m0_rows, m1_rows, m2_rows, day_rows = [], [], [], []
    per_season = []
    for target in TARGETS:
        tr = ok & np.isin(season, [s for s in SEASONS if s < target])
        te = ok & (season == target)
        if tr.sum() == 0 or te.sum() == 0:
            continue
        d1 = np.column_stack([np.ones(tr.sum()), logit(p_mkt[tr])])
        beta1 = fit_logistic(d1, over[tr].astype(float))
        d2 = np.column_stack([np.ones(tr.sum()), logit(p_mkt[tr]), logit(p_model[tr])])
        beta2 = fit_logistic(d2, over[tr].astype(float))

        e1 = np.column_stack([np.ones(te.sum()), logit(p_mkt[te])])
        e2 = np.column_stack([np.ones(te.sum()), logit(p_mkt[te]), logit(p_model[te])])
        q1 = predict_logistic(e1, beta1)
        q2 = predict_logistic(e2, beta2)

        y = over[te]
        ll0 = m.log_loss(np.column_stack([1 - p_mkt[te], p_mkt[te]]), y)
        ll1 = m.log_loss(np.column_stack([1 - q1, q1]), y)
        ll2 = m.log_loss(np.column_stack([1 - q2, q2]), y)
        print(f"{target:<11}{ll0:>10.4f}{ll1:>10.4f}{ll2:>16.4f}"
              f"{ll1 - ll0:>10.4f}{ll2 - ll1:>10.4f}")
        per_season.append({"target": target, "M0": ll0, "M1": ll1, "M2": ll2,
                           "M1-M0": ll1 - ll0, "M2-M1": ll2 - ll1,
                           "beta1": beta1.tolist(), "beta2": beta2.tolist()})

        m0_rows.append(row_ll(np.column_stack([1 - p_mkt[te], p_mkt[te]]), y))
        m1_rows.append(row_ll(np.column_stack([1 - q1, q1]), y))
        m2_rows.append(row_ll(np.column_stack([1 - q2, q2]), y))
        day_rows.append(days[np.where(te)[0]])

    m0 = np.concatenate(m0_rows)
    m1 = np.concatenate(m1_rows)
    m2 = np.concatenate(m2_rows)
    dd = np.concatenate(day_rows)

    d10 = boot(m1 - m0, dd)
    d21 = boot(m2 - m1, dd)
    print(f"\npooled M0 {m0.mean():.4f} | M1 {m1.mean():.4f} | M2 {m2.mean():.4f}")
    print(f"  M1 - M0 (market recalibration) : {d10[0]:+.4f}  95% CI [{d10[1]:+.4f}, {d10[2]:+.4f}]"
          f"  excludes 0: {d10[1] > 0 or d10[2] < 0}")
    print(f"  M2 - M1 (MODEL's contribution) : {d21[0]:+.4f}  95% CI [{d21[1]:+.4f}, {d21[2]:+.4f}]"
          f"  excludes 0: {d21[1] > 0 or d21[2] < 0}")

    # ---------------- de-margining sensitivity ----------------
    print("\n--- M1 with alternative market-probability inputs (rules out a de-margin artifact) ---")
    print("  (the two normalisations are the meaningful check; raw 1/odds is shown only")
    print("   to demonstrate it is not a probability and cannot be used as one)")
    for name, series in (
        ("proportional de-margin", p_mkt),
        ("power de-margin", p_mkt_pow),
        ("raw 1/odds (NOT a prob)", raw_over),
    ):
        rows1, rows0, dr = [], [], []
        for target in TARGETS:
            tr = ok & np.isin(season, [s for s in SEASONS if s < target])
            te = ok & (season == target)
            if tr.sum() == 0 or te.sum() == 0:
                continue
            b = fit_logistic(np.column_stack([np.ones(tr.sum()), logit(series[tr])]), over[tr].astype(float))
            q = predict_logistic(np.column_stack([np.ones(te.sum()), logit(series[te])]), b)
            y = over[te]
            rows1.append(row_ll(np.column_stack([1 - q, q]), y))
            rows0.append(row_ll(np.column_stack([1 - series[te], series[te]]), y))
            dr.append(days[np.where(te)[0]])
        a1, a0, ad = np.concatenate(rows1), np.concatenate(rows0), np.concatenate(dr)
        res = boot(a1 - a0, ad)
        print(f"  {name:<26} M0 {a0.mean():.4f} M1 {a1.mean():.4f} "
              f"M1-M0 {res[0]:+.4f} [{res[1]:+.4f}, {res[2]:+.4f}]")

    # ---------------- over-reaction probe ----------------
    print("\n--- over-reaction probe: M1 + last-5 / last-10 total goals ---")
    print(f"{'target':<11}{'b_mkt':>9}{'b_h5':>9}{'b_h10':>9}{'b_a5':>9}{'b_a10':>9}"
          f"{'probe':>10}{'M1':>10}{'probe-M1':>11}")
    probe_rows, m1b_rows, dayb_rows = [], [], []
    coefs = []
    for target in TARGETS:
        tr = ok & np.isin(season, [s for s in SEASONS if s < target])
        te = ok & (season == target)
        if tr.sum() == 0 or te.sum() == 0:
            continue

        def features(mask):
            idx = np.where(mask)[0]
            cutoffs = frame["cutoff"].to_numpy()[idx]
            h5 = np.full(len(idx), np.nan)
            h10 = np.full(len(idx), np.nan)
            a5 = np.full(len(idx), np.nan)
            a10 = np.full(len(idx), np.nan)
            cache: dict = {}
            for j, (i, cut) in enumerate(zip(idx, cutoffs)):
                if cut not in cache:
                    cache[cut] = form_table(pool, pd.Timestamp(cut))
                table = cache[cut]
                home = frame["team_home"].to_numpy()[i]
                away = frame["team_away"].to_numpy()[i]
                h5[j] = table[("home", 5)].get(home, np.nan)
                h10[j] = table[("home", 10)].get(home, np.nan)
                a5[j] = table[("away", 5)].get(away, np.nan)
                a10[j] = table[("away", 10)].get(away, np.nan)
            return h5, h10, a5, a10

        h5t, h10t, a5t, a10t = features(tr)
        h5e, h10e, a5e, a10e = features(te)
        valid_tr = np.isfinite(h5t) & np.isfinite(h10t) & np.isfinite(a5t) & np.isfinite(a10t)
        valid_te = np.isfinite(h5e) & np.isfinite(h10e) & np.isfinite(a5e) & np.isfinite(a10e)

        design_tr = np.column_stack([
            np.ones(valid_tr.sum()), logit(p_mkt[tr][valid_tr]),
            h5t[valid_tr], h10t[valid_tr], a5t[valid_tr], a10t[valid_tr],
        ])
        beta = fit_logistic(design_tr, over[tr][valid_tr].astype(float))
        design_te = np.column_stack([
            np.ones(valid_te.sum()), logit(p_mkt[te][valid_te]),
            h5e[valid_te], h10e[valid_te], a5e[valid_te], a10e[valid_te],
        ])
        q = predict_logistic(design_te, beta)
        y = over[te][valid_te]
        ll_probe = m.log_loss(np.column_stack([1 - q, q]), y)

        b1 = fit_logistic(np.column_stack([np.ones(valid_tr.sum()), logit(p_mkt[tr][valid_tr])]),
                          over[tr][valid_tr].astype(float))
        q1 = predict_logistic(np.column_stack([np.ones(valid_te.sum()), logit(p_mkt[te][valid_te])]), b1)
        ll_m1 = m.log_loss(np.column_stack([1 - q1, q1]), y)

        print(f"{target:<11}{beta[1]:>9.3f}{beta[2]:>9.3f}{beta[3]:>9.3f}"
              f"{beta[4]:>9.3f}{beta[5]:>9.3f}{ll_probe:>10.4f}{ll_m1:>10.4f}"
              f"{ll_probe - ll_m1:>11.4f}")
        coefs.append({"target": target, "b_mkt": beta[1], "b_h5": beta[2], "b_h10": beta[3],
                      "b_a5": beta[4], "b_a10": beta[5], "probe": ll_probe, "M1": ll_m1})
        probe_rows.append(row_ll(np.column_stack([1 - q, q]), y))
        m1b_rows.append(row_ll(np.column_stack([1 - q1, q1]), y))
        dayb_rows.append(days[np.where(te)[0]][valid_te])

    pr = np.concatenate(probe_rows)
    m1b = np.concatenate(m1b_rows)
    db = np.concatenate(dayb_rows)
    res = boot(pr - m1b, db)
    print(f"\npooled probe {pr.mean():.4f} | M1 {m1b.mean():.4f} | probe - M1 "
          f"{res[0]:+.4f} 95% CI [{res[1]:+.4f}, {res[2]:+.4f}] "
          f"excludes 0: {res[1] > 0 or res[2] < 0}")

    cf = pd.DataFrame(coefs)
    print("\ncoefficient stability across seasons:")
    for col in ("b_mkt", "b_h5", "b_h10", "b_a5", "b_a10"):
        signs = np.sign(cf[col].to_numpy())
        print(f"  {col:<7} mean {cf[col].mean():+.4f}  sd {cf[col].std():.4f}  "
              f"signs {signs.tolist()}  consistent: {abs(signs.sum()) == len(signs)}")

    # ---------------- verdict ----------------
    print("\n" + "=" * 96)
    print("VERDICT")
    recal = d10[1] > 0 or d10[2] < 0
    model_adds = d21[1] > 0 or d21[2] < 0
    probe_adds = res[1] > 0 or res[2] < 0
    print(f"  market recalibration (M1-M0) significant : {recal} ({d10[0]:+.4f})")
    print(f"  model contribution   (M2-M1) significant : {model_adds} ({d21[0]:+.4f})")
    print(f"  recent-scoring probe (probe-M1) significant: {probe_adds} ({res[0]:+.4f})")
    if recal and not model_adds and not probe_adds:
        print("  -> a stable O/U market bias exists, but it is RECALIBRATION ONLY;")
        print("     it is NOT tied to recent scoring and the model adds nothing.")
    elif recal and probe_adds:
        print("  -> the bias is at least partly tied to recent scoring (over-reaction).")
    else:
        print("  -> no stable O/U market bias detected.")

    pd.DataFrame(per_season).to_csv("reports/figures/totals_decomposition.csv", index=False)
    cf.to_csv("reports/figures/totals_overreaction_coefs.csv", index=False)
    pd.DataFrame([
        {"metric": "M1_minus_M0", "value": d10[0], "ci_low": d10[1], "ci_high": d10[2]},
        {"metric": "M2_minus_M1", "value": d21[0], "ci_low": d21[1], "ci_high": d21[2]},
        {"metric": "probe_minus_M1", "value": res[0], "ci_low": res[1], "ci_high": res[2]},
        {"metric": "M0_pooled", "value": float(m0.mean()), "ci_low": np.nan, "ci_high": np.nan},
        {"metric": "M1_pooled", "value": float(m1.mean()), "ci_low": np.nan, "ci_high": np.nan},
        {"metric": "M2_pooled", "value": float(m2.mean()), "ci_low": np.nan, "ci_high": np.nan},
        {"metric": "probe_pooled", "value": float(pr.mean()), "ci_low": np.nan, "ci_high": np.nan},
    ]).to_csv("reports/figures/totals_pooled.csv", index=False)

    ledger.log_evaluation(
        league=FINAL.league, market="OU2.5", selection="over/under",
        rule_config=f"TOTALS STRESS TEST {FINAL.config_id}",
        split="discovery:walk-forward", n_predictions=len(m0),
        log_loss=float(m2.mean()), brier="",
        benchmark_name="market_prematch", benchmark_log_loss=float(m0.mean()),
        n_bets="", roi="", mean_clv="",
        notes=(f"M1-M0 {d10[0]:+.4f} CI [{d10[1]:+.4f},{d10[2]:+.4f}]; "
               f"M2-M1 {d21[0]:+.4f} CI [{d21[1]:+.4f},{d21[2]:+.4f}]; "
               f"probe-M1 {res[0]:+.4f} CI [{res[1]:+.4f},{res[2]:+.4f}]"),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())