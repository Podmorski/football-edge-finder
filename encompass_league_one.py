"""Step 6 — encompassing / blend test: does the model add information?

1X2:      q ∝ p_mkt^a * p_model^b   (p_mkt = de-margined PRE-MATCH market, the
          price actually available at bet time)
O/U 2.5:  logistic regression on logit(p_mkt) and logit(p_model)

Strictly walk-forward by season: for target season T, a/b are fitted on all
EARLIER discovery seasons only (first target 2018-19, trained on 2017-18).

Pre-registered reading (written before running):
  the model ADDS INFORMATION only if the pooled out-of-sample blend beats the
  market pre-match with the bootstrap CI of the difference excluding 0.

No ROI, no bet simulation, no "edge" language.
"""

from __future__ import annotations

import sys

import numpy as np
import pandas as pd
from scipy.optimize import minimize

from core import ledger, odds, walkforward as wf
from models import league_one_dixon_coles as m

SEASONS = ["2017-2018", "2018-2019", "2019-2020", "2020-2021", "2021-2022", "2022-2023"]
TARGETS = ["2018-2019", "2019-2020", "2020-2021", "2021-2022", "2022-2023"]
FINAL = wf.Config(xi=0.002, covid_mode="exclude_after", newcomer="newcomer_prior")

BOOTSTRAP_N = 2000
SEED = 20260923
EPS = 1e-9


def outcome(frame: pd.DataFrame) -> np.ndarray:
    fthg, ftag = frame["fthg"].to_numpy(), frame["ftag"].to_numpy()
    out = np.full(len(frame), 1, dtype=int)
    out[fthg > ftag] = 0
    out[fthg < ftag] = 2
    return out


def row_ll(probs: np.ndarray, actual: np.ndarray) -> np.ndarray:
    return -np.log(np.clip(probs[np.arange(len(actual)), actual], 1e-15, 1.0))


def blend_1x2(p_mkt: np.ndarray, p_model: np.ndarray, a: float, b: float) -> np.ndarray:
    q = np.power(np.clip(p_mkt, EPS, 1.0), a) * np.power(np.clip(p_model, EPS, 1.0), b)
    return q / q.sum(axis=1, keepdims=True)


def fit_1x2(p_mkt: np.ndarray, p_model: np.ndarray, actual: np.ndarray) -> tuple[float, float]:
    def objective(params):
        a, b = params
        probs = blend_1x2(p_mkt, p_model, a, b)
        return row_ll(probs, actual).mean()

    result = minimize(objective, x0=[1.0, 1.0], method="Nelder-Mead",
                      options={"xatol": 1e-6, "fatol": 1e-10, "maxiter": 2000})
    return float(result.x[0]), float(result.x[1])


def logit(p: np.ndarray) -> np.ndarray:
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return np.log(p / (1 - p))


def fit_logistic(x_mkt: np.ndarray, x_model: np.ndarray, y: np.ndarray):
    """Logistic regression on [logit(mkt), logit(model)] with an intercept."""
    design = np.column_stack([np.ones_like(x_mkt), x_mkt, x_model])

    def objective(beta):
        z = design @ beta
        return float(np.mean(np.logaddexp(0.0, z) - y * z))

    result = minimize(objective, x0=np.zeros(3), method="Nelder-Mead",
                      options={"xatol": 1e-7, "fatol": 1e-11, "maxiter": 4000})
    return result.x


def main() -> int:
    pool = wf.load_pool(FINAL.league)
    preds = wf.run(FINAL, SEASONS, pool=pool)
    raw = pool.reset_index().rename(columns={"index": "row", "id": "match_key"})
    odds_columns = ["avg_h", "avg_d", "avg_a", "bb_av_h", "bb_av_d", "bb_av_a",
                    "psch", "pscd", "psca", "avg>2.5", "avg<2.5", "bb_av>2.5", "bb_av<2.5"]
    frame = preds.merge(raw[["match_key"] + odds_columns], on="match_key", how="left")

    prem = odds.prematch_1x2(frame)
    sharp = odds.sharp_closing_1x2(frame)
    p_mkt = odds.demargin(prem.odds.where(prem.available)).to_numpy()
    p_sharp = odds.demargin(sharp.odds.where(sharp.available)).to_numpy()
    p_model = frame[["p_home", "p_draw", "p_away"]].to_numpy()
    actual = outcome(frame)
    days = frame["date"].to_numpy()
    season = frame["season"].to_numpy()

    keep = np.isfinite(p_mkt).all(axis=1)
    print("=" * 96)
    print("Step 6 — encompassing / blend test (walk-forward by season)")
    print("=" * 96)
    print(f"rows with a pre-match market price: {int(keep.sum())}/{len(frame)}")

    print("\n--- 1X2: q ~ p_mkt^a * p_model^b ---")
    print(f"{'target':<11}{'train seas.':>13}{'a':>9}{'b':>9}{'blend':>10}"
          f"{'mkt pre':>10}{'SHARP':>10}{'blend-mkt':>11}")

    blend_loss, mkt_loss, sharp_loss, target_rows = [], [], [], []
    per_season = []
    for target in TARGETS:
        train_mask = keep & np.isin(season, [s for s in SEASONS if s < target])
        test_mask = keep & (season == target)
        if train_mask.sum() == 0 or test_mask.sum() == 0:
            continue
        a, b = fit_1x2(p_mkt[train_mask], p_model[train_mask], actual[train_mask])

        q = blend_1x2(p_mkt[test_mask], p_model[test_mask], a, b)
        ll_blend = m.log_loss(q, actual[test_mask])
        ll_mkt = m.log_loss(p_mkt[test_mask], actual[test_mask])
        sharp_ok = np.isfinite(p_sharp[test_mask]).all(axis=1)
        ll_sharp = (
            m.log_loss(p_sharp[test_mask][sharp_ok], actual[test_mask][sharp_ok])
            if sharp_ok.any() else float("nan")
        )
        print(f"{target:<11}{len(set(season[train_mask])):>13}{a:>9.4f}{b:>9.4f}"
              f"{ll_blend:>10.4f}{ll_mkt:>10.4f}{ll_sharp:>10.4f}{ll_blend - ll_mkt:>11.4f}")
        per_season.append({"target": target, "a": a, "b": b, "blend": ll_blend,
                           "market": ll_mkt, "sharp": ll_sharp})

        # Pool all three on the SAME rows (those with a SHARP price available).
        idx = np.where(test_mask)[0][sharp_ok]
        if len(idx) == 0:
            continue
        blend_loss.append(row_ll(q[sharp_ok], actual[test_mask][sharp_ok]))
        mkt_loss.append(row_ll(p_mkt[test_mask][sharp_ok], actual[test_mask][sharp_ok]))
        sharp_loss.append(row_ll(p_sharp[test_mask][sharp_ok], actual[test_mask][sharp_ok]))
        target_rows.append(days[idx])

    bl = np.concatenate(blend_loss)
    ml = np.concatenate(mkt_loss)
    sl = np.concatenate(sharp_loss)
    dd = np.concatenate(target_rows)

    def boot(diff, day_values, n=BOOTSTRAP_N, seed=SEED):
        rng = np.random.default_rng(seed)
        unique, inverse = np.unique(day_values, return_inverse=True)
        groups = [np.where(inverse == i)[0] for i in range(len(unique))]
        draws = np.empty(n)
        for i in range(n):
            picks = rng.integers(0, len(groups), len(groups))
            idx = np.concatenate([groups[p] for p in picks])
            draws[i] = diff[idx].mean()
        return float(diff.mean()), float(np.percentile(draws, 2.5)), float(np.percentile(draws, 97.5))

    obs_mkt, lo_mkt, hi_mkt = boot(bl - ml, dd)
    obs_sharp, lo_sharp, hi_sharp = boot(bl - sl, dd)
    print(f"\npooled out-of-sample: blend {bl.mean():.4f} | market {ml.mean():.4f} | SHARP {sl.mean():.4f}")
    print(f"  blend - market : {obs_mkt:+.4f}  95% CI [{lo_mkt:+.4f}, {hi_mkt:+.4f}]"
          f"  -> excludes 0: {lo_mkt > 0 or hi_mkt < 0}")
    print(f"  blend - SHARP  : {obs_sharp:+.4f}  95% CI [{lo_sharp:+.4f}, {hi_sharp:+.4f}]"
          f"  -> excludes 0: {lo_sharp > 0 or hi_sharp < 0}")

    # pooled b with bootstrap CI
    a_all, b_all = fit_1x2(p_mkt[keep], p_model[keep], actual[keep])
    rng = np.random.default_rng(SEED)
    unique, inverse = np.unique(days[keep], return_inverse=True)
    groups = [np.where(inverse == i)[0] for i in range(len(unique))]
    bs = np.empty(BOOTSTRAP_N)
    for i in range(BOOTSTRAP_N):
        picks = rng.integers(0, len(groups), len(groups))
        idx = np.concatenate([groups[p] for p in picks])
        _, bs[i] = fit_1x2(p_mkt[keep][idx], p_model[keep][idx], actual[keep][idx])
    print(f"\npooled fit: a={a_all:.4f}, b={b_all:.4f} | b 95% CI "
          f"[{np.percentile(bs, 2.5):.4f}, {np.percentile(bs, 97.5):.4f}]")

    # ---------------- O/U logistic ----------------
    ou = odds.prematch_ou25(frame)
    # BY NAME: ou.odds columns are ("over", "under"); [:, 1] would be UNDER.
    ou_mkt = odds.demargin(ou.odds.where(ou.available))["over"].to_numpy()
    p_model_ou = frame["p_over25"].to_numpy()
    over = (frame["fthg"] + frame["ftag"] > 2.5).to_numpy().astype(float)
    ok = np.isfinite(ou_mkt)

    print(f"\n--- O/U 2.5: logistic on logit(p_mkt), logit(p_model) ---")
    print(f"{'target':<11}{'b0':>9}{'b_mkt':>9}{'b_model':>9}{'blend':>10}{'market':>10}{'blend-mkt':>11}")
    ou_rows, ou_blend, ou_mkt_loss, ou_days = [], [], [], []
    for target in TARGETS:
        train_mask = ok & np.isin(season, [s for s in SEASONS if s < target])
        test_mask = ok & (season == target)
        if train_mask.sum() == 0 or test_mask.sum() == 0:
            continue
        beta = fit_logistic(logit(ou_mkt[train_mask]), logit(p_model_ou[train_mask]), over[train_mask])
        design = np.column_stack([np.ones(test_mask.sum()), logit(ou_mkt[test_mask]),
                                  logit(p_model_ou[test_mask])])
        q = 1.0 / (1.0 + np.exp(-(design @ beta)))
        probs_blend = np.column_stack([1 - q, q])
        probs_mkt = np.column_stack([1 - ou_mkt[test_mask], ou_mkt[test_mask]])
        y = over[test_mask].astype(int)
        ll_blend = m.log_loss(probs_blend, y)
        ll_mkt = m.log_loss(probs_mkt, y)
        print(f"{target:<11}{beta[0]:>9.4f}{beta[1]:>9.4f}{beta[2]:>9.4f}"
              f"{ll_blend:>10.4f}{ll_mkt:>10.4f}{ll_blend - ll_mkt:>11.4f}")
        ou_rows.append({"target": target, "b0": beta[0], "b_mkt": beta[1], "b_model": beta[2],
                        "blend": ll_blend, "market": ll_mkt})
        ou_blend.append(row_ll(probs_blend, y))
        ou_mkt_loss.append(row_ll(probs_mkt, y))
        ou_days.append(days[np.where(test_mask)[0]])

    obl = np.concatenate(ou_blend)
    oml = np.concatenate(ou_mkt_loss)
    od = np.concatenate(ou_days)
    o_obs, o_lo, o_hi = boot(obl - oml, od)
    print(f"\npooled O/U: blend {obl.mean():.4f} | market {oml.mean():.4f} | diff "
          f"{o_obs:+.4f} 95% CI [{o_lo:+.4f}, {o_hi:+.4f}] -> excludes 0: {o_lo > 0 or o_hi < 0}")

    # ---------------- verdict ----------------
    adds = lo_mkt > 0 or hi_mkt < 0
    print("\n" + "=" * 96)
    print("VERDICT (pre-registered): the model ADDS INFORMATION only if the pooled")
    print("out-of-sample blend beats market pre-match with the CI of the difference")
    print("excluding 0.")
    print(f"  blend - market = {obs_mkt:+.4f} [{lo_mkt:+.4f}, {hi_mkt:+.4f}]")
    print(f"  -> {'ADDS INFORMATION' if (adds and obs_mkt < 0) else 'DOES NOT ADD INFORMATION'}")
    print(f"  (a positive difference means the blend is WORSE than the market alone)")

    pd.DataFrame(per_season).to_csv("reports/figures/league_one_blend_1x2.csv", index=False)
    pd.DataFrame(ou_rows).to_csv("reports/figures/league_one_blend_ou25.csv", index=False)

    ledger.log_evaluation(
        league=FINAL.league,
        market="1X2+OU2.5",
        selection="blend",
        rule_config=f"ENCOMPASSING {FINAL.config_id}",
        split="discovery:walk-forward",
        n_predictions=len(bl),
        log_loss=float(bl.mean()),
        brier="",
        benchmark_name="market_prematch",
        benchmark_log_loss=float(ml.mean()),
        n_bets="",
        roi="",
        mean_clv="",
        notes=(
            f"blend-market {obs_mkt:+.4f} CI [{lo_mkt:+.4f},{hi_mkt:+.4f}]; "
            f"pooled b={b_all:.4f}; O/U diff {o_obs:+.4f} CI [{o_lo:+.4f},{o_hi:+.4f}]"
        ),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())