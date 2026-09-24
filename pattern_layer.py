"""Step 2 — pattern layer (the "low-scoring profile" idea).

Leakage-free features at each cutoff (window 10 pre-registered; 20 as sensitivity):
  league_over   league over-2.5 rate over the last W matchdays
  home_gf/ga    home team's rolling HOME goals for / against
  home_over     home team's rolling HOME over-2.5 rate
  away_gf/ga    away team's rolling AWAY goals for / against
  away_over     away team's rolling AWAY over-2.5 rate

Walk-forward logistic for over 2.5 on
  (a) logit(model P(over))  + features
  (b) logit(market P(over)) + features
The layer adds information only if pooled out-of-sample log loss beats its base
with the bootstrap 95% CI excluding 0.

Then descriptive rule tables for the bottom-third / top-third profiles.
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

WINDOW = 10
SENSITIVITY_WINDOW = 20
BOOTSTRAP_N = 2000
SEED = 20260924

ODDS_COLUMNS = ["avg>2.5", "avg<2.5", "bb_av>2.5", "bb_av<2.5", "b365>2.5", "b365<2.5"]


def logit(p):
    p = np.clip(np.asarray(p, dtype=float), 1e-6, 1 - 1e-6)
    return np.log(p / (1 - p))


def row_ll(probs, y):
    return -np.log(np.clip(probs[np.arange(len(y)), y], 1e-15, 1.0))


def fit_logistic(design, y):
    def objective(beta):
        z = design @ beta
        return float(np.mean(np.logaddexp(0.0, z) - y * z))

    return minimize(objective, x0=np.zeros(design.shape[1]), method="Nelder-Mead",
                    options={"xatol": 1e-7, "fatol": 1e-11, "maxiter": 8000}).x


def predict_logistic(design, beta):
    return 1.0 / (1.0 + np.exp(-(design @ beta)))


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


def wilson(k, n, z=1.96):
    if n == 0:
        return (float("nan"), float("nan"))
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (centre - half, centre + half)


def build_features(pool: pd.DataFrame, cutoff: pd.Timestamp, window: int) -> dict:
    """All features for one cutoff, computed strictly from data before it."""
    sub = pool[pool["date"] < cutoff]
    dates = np.sort(sub["date"].unique())
    recent_dates = dates[-window:] if len(dates) >= window else dates
    recent = sub[sub["date"].isin(recent_dates)]
    league_over = float(((recent["fthg"] + recent["ftag"]) > 2.5).mean()) if len(recent) else np.nan

    out = {"league_over": league_over}
    for venue, column, prefix in (("home", "team_home", "home"), ("away", "team_away", "away")):
        tail = sub.sort_values("date").groupby(column).tail(window)
        grouped = tail.groupby(column)
        gf = grouped.apply(
            lambda g: g["fthg"].mean() if venue == "home" else g["ftag"].mean(),
            include_groups=False,
        )
        ga = grouped.apply(
            lambda g: g["ftag"].mean() if venue == "home" else g["fthg"].mean(),
            include_groups=False,
        )
        over = grouped.apply(
            lambda g: float(((g["fthg"] + g["ftag"]) > 2.5).mean()), include_groups=False
        )
        out[f"{prefix}_gf"] = gf.to_dict()
        out[f"{prefix}_ga"] = ga.to_dict()
        out[f"{prefix}_over"] = over.to_dict()
    return out


def feature_matrix(frame: pd.DataFrame, pool: pd.DataFrame, mask: np.ndarray, window: int):
    idx = np.where(mask)[0]
    cutoffs = frame["cutoff"].to_numpy()[idx]
    home = frame["team_home"].to_numpy()[idx]
    away = frame["team_away"].to_numpy()[idx]
    cols = {k: np.full(len(idx), np.nan) for k in
            ("league_over", "home_gf", "home_ga", "home_over", "away_gf", "away_ga", "away_over")}
    cache: dict = {}
    for j, cut in enumerate(cutoffs):
        if cut not in cache:
            cache[cut] = build_features(pool, pd.Timestamp(cut), window)
        f = cache[cut]
        cols["league_over"][j] = f["league_over"]
        cols["home_gf"][j] = f["home_gf"].get(home[j], np.nan)
        cols["home_ga"][j] = f["home_ga"].get(home[j], np.nan)
        cols["home_over"][j] = f["home_over"].get(home[j], np.nan)
        cols["away_gf"][j] = f["away_gf"].get(away[j], np.nan)
        cols["away_ga"][j] = f["away_ga"].get(away[j], np.nan)
        cols["away_over"][j] = f["away_over"].get(away[j], np.nan)
    return cols


def run_layer(frame, pool, p_base, over, season, days, ok, window, label):
    """Walk-forward: base alone vs base + features. Returns pooled losses + CI."""
    base_rows, layer_rows, day_rows, coefs = [], [], [], []
    for target in TARGETS:
        tr = ok & np.isin(season, [s for s in SEASONS if s < target])
        te = ok & (season == target)
        if tr.sum() == 0 or te.sum() == 0:
            continue
        ftr = feature_matrix(frame, pool, tr, window)
        fte = feature_matrix(frame, pool, te, window)
        keys = list(ftr)
        vtr = np.ones(int(tr.sum()), dtype=bool)
        vte = np.ones(int(te.sum()), dtype=bool)
        for k in keys:
            vtr &= np.isfinite(ftr[k])
            vte &= np.isfinite(fte[k])

        xb_tr = logit(p_base[tr][vtr])
        xb_te = logit(p_base[te][vte])
        ytr = over[tr][vtr].astype(float)
        yte = over[te][vte]

        b0 = fit_logistic(np.column_stack([np.ones(vtr.sum()), xb_tr]), ytr)
        q0 = predict_logistic(np.column_stack([np.ones(vte.sum()), xb_te]), b0)

        design_tr = np.column_stack([np.ones(vtr.sum()), xb_tr] + [ftr[k][vtr] for k in keys])
        design_te = np.column_stack([np.ones(vte.sum()), xb_te] + [fte[k][vte] for k in keys])
        b1 = fit_logistic(design_tr, ytr)
        q1 = predict_logistic(design_te, b1)

        base_rows.append(row_ll(np.column_stack([1 - q0, q0]), yte))
        layer_rows.append(row_ll(np.column_stack([1 - q1, q1]), yte))
        day_rows.append(days[np.where(te)[0]][vte])
        coefs.append({"target": target, **{k: v for k, v in zip(["b0", "b_base"] + keys, b1)}})

    base = np.concatenate(base_rows)
    layer = np.concatenate(layer_rows)
    dd = np.concatenate(day_rows)
    res = boot(layer - base, dd)
    print(f"\n  [{label}] base {base.mean():.4f} | +features {layer.mean():.4f} | "
          f"diff {res[0]:+.4f} 95% CI [{res[1]:+.4f}, {res[2]:+.4f}] "
          f"excludes 0: {res[1] > 0 or res[2] < 0}")
    return pd.DataFrame(coefs), res


def main() -> int:
    pool = wf.load_pool(FINAL.league)
    preds = wf.run(FINAL, SEASONS, pool=pool)
    raw = pool.reset_index().rename(columns={"index": "row", "id": "match_key"})
    frame = preds.merge(raw[["match_key"] + ODDS_COLUMNS], on="match_key", how="left")

    ou = odds.prematch_ou25(frame)
    # Index the O/U market BY NAME: ou.odds columns are ("over", "under"), so
    # positional [:, 1] would silently select UNDER.
    p_mkt = odds.demargin(ou.odds.where(ou.available), "proportional")["over"].to_numpy()
    p_model = frame["p_over25"].to_numpy()
    total = (frame["fthg"] + frame["ftag"]).to_numpy()
    over = (total > 2.5).astype(int)
    days = frame["date"].to_numpy()
    season = frame["season"].to_numpy()
    ok = np.isfinite(p_mkt)
    under_odds = ou.odds["under"].to_numpy(dtype=float)

    print("=" * 96)
    print("Step 2 — pattern layer")
    print("=" * 96)

    print(f"\n--- walk-forward layer, window {WINDOW} (pre-registered) ---")
    coefs_model, res_model = run_layer(frame, pool, p_model, over, season, days, ok, WINDOW,
                                       "base = model P(over)")
    coefs_mkt, res_mkt = run_layer(frame, pool, p_mkt, over, season, days, ok, WINDOW,
                                   "base = market P(over)")

    print(f"\n--- sensitivity only: window {SENSITIVITY_WINDOW} ---")
    _, res_model20 = run_layer(frame, pool, p_model, over, season, days, ok, SENSITIVITY_WINDOW,
                               "base = model P(over)")
    _, res_mkt20 = run_layer(frame, pool, p_mkt, over, season, days, ok, SENSITIVITY_WINDOW,
                             "base = market P(over)")

    print("\n--- coefficients (window 10, base = market P(over)) ---")
    print(coefs_mkt.to_string(index=False, float_format=lambda v: f"{v:+.3f}"))

    # ---------------- descriptive rule tables ----------------
    print("\n" + "=" * 96)
    print("Descriptive rule tables (window 10)")
    print("=" * 96)
    feats = feature_matrix(frame, pool, ok, WINDOW)
    home_over = feats["home_over"]
    away_over = feats["away_over"]
    valid = np.isfinite(home_over) & np.isfinite(away_over)
    lo_h, hi_h = np.nanpercentile(home_over[valid], [33.333, 66.667])
    lo_a, hi_a = np.nanpercentile(away_over[valid], [33.333, 66.667])
    print(f"  home_over terciles: {lo_h:.3f} / {hi_h:.3f}   away_over terciles: {lo_a:.3f} / {hi_a:.3f}")

    # feature arrays are restricted to the ok rows, so filter everything to match
    over_ok = over[ok]
    p_model_ok = p_model[ok]
    p_mkt_ok = p_mkt[ok]
    p_under_model = 1 - p_model_ok
    p_under_mkt = 1 - p_mkt_ok
    under_odds_ok = under_odds[ok]
    over_odds_ok = ou.odds["over"].to_numpy(dtype=float)[ok]

    rule_rows = []
    for name, mask, side in (
        ("both bottom third -> UNDER 2.5", valid & (home_over <= lo_h) & (away_over <= lo_a), "under"),
        ("both top third    -> OVER 2.5", valid & (home_over >= hi_h) & (away_over >= hi_a), "over"),
    ):
        n = int(mask.sum())
        if side == "under":
            hits = int((over_ok[mask] == 0).sum())
            p_mod = float(p_under_model[mask].mean())
            p_mkt_side = float(p_under_mkt[mask].mean())
            odds_side = float(np.nanmean(under_odds_ok[mask]))
        else:
            hits = int((over_ok[mask] == 1).sum())
            p_mod = float(p_model_ok[mask].mean())
            p_mkt_side = float(p_mkt_ok[mask].mean())
            odds_side = float(np.nanmean(over_odds_ok[mask]))
        ci = wilson(hits, n)
        be = 1.0 / odds_side if odds_side and np.isfinite(odds_side) else float("nan")
        clears = ci[0] > be if np.isfinite(be) else False
        print(f"\n  {name}")
        print(f"    n = {n}")
        print(f"    observed hit rate = {hits / n:.4f}  95% CI [{ci[0]:.4f}, {ci[1]:.4f}]")
        print(f"    mean model P(side) = {p_mod:.4f} | mean market P(side) = {p_mkt_side:.4f}")
        print(f"    mean market-average odds = {odds_side:.3f} | break-even = {be:.4f}")
        print(f"    hit-rate CI above break-even: {clears}")
        rule_rows.append({
            "rule": name, "side": side, "n": n, "hits": hits,
            "hit_rate": hits / n, "ci_low": ci[0], "ci_high": ci[1],
            "mean_model_p": p_mod, "mean_market_p": p_mkt_side,
            "mean_odds": odds_side, "break_even": be, "clears_break_even": clears,
        })

    pd.DataFrame(rule_rows).to_csv("reports/figures/pattern_rule_tables.csv", index=False)

    print("\n--- verdict ---")
    # The layer adds information only if it IMPROVES on its base (negative diff)
    # with the bootstrap CI excluding 0.
    adds_model = (res_model[0] < 0) and (res_model[2] < 0)
    adds_mkt = (res_mkt[0] < 0) and (res_mkt[2] < 0)
    print(f"  layer on model base  improves on base: {adds_model} "
          f"(diff {res_model[0]:+.4f}, CI [{res_model[1]:+.4f}, {res_model[2]:+.4f}])")
    print(f"  layer on market base improves on base: {adds_mkt} "
          f"(diff {res_mkt[0]:+.4f}, CI [{res_mkt[1]:+.4f}, {res_mkt[2]:+.4f}])")
    print("  a POSITIVE diff means the layer makes predictions WORSE.")
    if not adds_model and not adds_mkt:
        print("  -> the pattern layer adds NO information; it degrades both bases.")

    coefs_model.to_csv("reports/figures/pattern_layer_coefs_model.csv", index=False)
    coefs_mkt.to_csv("reports/figures/pattern_layer_coefs_market.csv", index=False)
    pd.DataFrame([
        {"metric": "layer_model_diff", "value": res_model[0],
         "ci_low": res_model[1], "ci_high": res_model[2]},
        {"metric": "layer_market_diff", "value": res_mkt[0],
         "ci_low": res_mkt[1], "ci_high": res_mkt[2]},
        {"metric": "layer_model_diff_w20", "value": res_model20[0],
         "ci_low": res_model20[1], "ci_high": res_model20[2]},
        {"metric": "layer_market_diff_w20", "value": res_mkt20[0],
         "ci_low": res_mkt20[1], "ci_high": res_mkt20[2]},
    ]).to_csv("reports/figures/pattern_layer_pooled.csv", index=False)

    ledger.log_evaluation(
        league=FINAL.league, market="OU2.5", selection="over/under",
        rule_config=f"PATTERN LAYER w={WINDOW} {FINAL.config_id}",
        split="discovery:walk-forward", n_predictions=int(ok.sum()),
        log_loss=float(res_mkt[0]), brier="",
        benchmark_name="market_prematch_base", benchmark_log_loss="",
        n_bets="", roi="", mean_clv="",
        notes=(f"layer-model diff {res_model[0]:+.4f} CI [{res_model[1]:+.4f},{res_model[2]:+.4f}]; "
               f"layer-market diff {res_mkt[0]:+.4f} CI [{res_mkt[1]:+.4f},{res_mkt[2]:+.4f}]"),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())