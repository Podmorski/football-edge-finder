"""Step 3 — extend the fixed League One config to the other leagues.

Config is TRANSFERRED, not re-tuned: xi=0.002, covid_mode=exclude_after,
newcomer=newcomer_prior. Discovery seasons only; confirmation never touched.

Per league:
  (a) 1X2 model vs naive vs market pre-match vs Pinnacle close, per season and
      pooled, paired bootstrap 95% CIs (2000, by matchday)
  (b) 1X2 blend: b coefficient and blend-minus-market CI (diagnostic)
  (c) totals: tripwire check, M0 vs constant, M1-M0, M2-M1 with CIs
  (d) 22-market combo calibration, ranked by log-loss gain + slope
  (e) payout check at market average and Pinnacle, with bins inspected

Then a cross-league table and the pre-registered candidate reading.
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
LEAGUES = ["ligue_2_t2", "bundesliga_2", "bundesliga_1"]
FINAL = wf.Config(xi=0.002, covid_mode="exclude_after", newcomer="newcomer_prior")

BOOTSTRAP_N = 2000
SEED = 20260924
BINS = 10

ODDS_COLUMNS = [
    "avg_h", "avg_d", "avg_a", "bb_av_h", "bb_av_d", "bb_av_a",
    "b365_h", "b365_d", "b365_a", "psh", "psd", "psa",
    "psch", "pscd", "psca", "avg>2.5", "avg<2.5", "bb_av>2.5", "bb_av<2.5",
    "b365>2.5", "b365<2.5", "p>2.5", "p<2.5",
]

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


def logit(p):
    p = np.clip(np.asarray(p, dtype=float), 1e-6, 1 - 1e-6)
    return np.log(p / (1 - p))


def row_ll(probs, y):
    return -np.log(np.clip(probs[np.arange(len(y)), y], 1e-15, 1.0))


def outcome(frame):
    fthg, ftag = frame["fthg"].to_numpy(), frame["ftag"].to_numpy()
    out = np.full(len(frame), 1, dtype=int)
    out[fthg > ftag] = 0
    out[fthg < ftag] = 2
    return out


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


def fit_logistic(design, y):
    def objective(beta):
        z = design @ beta
        return float(np.mean(np.logaddexp(0.0, z) - y * z))

    return minimize(objective, x0=np.zeros(design.shape[1]), method="Nelder-Mead",
                    options={"xatol": 1e-7, "fatol": 1e-11, "maxiter": 6000}).x


def predict_logistic(design, beta):
    return 1.0 / (1.0 + np.exp(-(design @ beta)))


def fit_blend(p_mkt, p_model, actual):
    """Two-parameter power blend q ~ p_mkt^a * p_model^b (no intercept).

    A 3-parameter logistic version diverges (b -> 1e255) because the objective
    is flat and unbounded in the intercept direction.
    """
    def objective(params):
        a, b = params
        q = np.power(np.clip(p_mkt, 1e-9, 1.0), a) * np.power(np.clip(p_model, 1e-9, 1.0), b)
        q = q / q.sum(axis=1, keepdims=True)
        return row_ll(q, actual).mean()

    res = minimize(objective, x0=[1.0, 1.0], method="Nelder-Mead",
                   options={"xatol": 1e-6, "fatol": 1e-10, "maxiter": 2000})
    return float(res.x[0]), float(res.x[1])


def wilson(k, n, z=1.96):
    if n == 0:
        return (float("nan"), float("nan"))
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (centre - half, centre + half)


def evaluate_league(slug: str, results: dict, candidates: list) -> None:
    cfg = wf.Config(league=slug, xi=0.002, covid_mode="exclude_after", newcomer="newcomer_prior")
    pool = wf.load_pool(slug)
    preds = wf.run(cfg, SEASONS, pool=pool)
    raw = pool.reset_index().rename(columns={"index": "row", "id": "match_key"})
    frame = preds.merge(raw[["match_key"] + ODDS_COLUMNS], on="match_key", how="left")

    actual = outcome(frame)
    days = frame["date"].to_numpy()
    season = frame["season"].to_numpy()
    total = (frame["fthg"] + frame["ftag"]).to_numpy()
    over = (total > 2.5).astype(int)

    print("\n" + "=" * 100)
    print(f"LEAGUE {slug}  ({len(frame)} predictions)")
    print("=" * 100)

    # ---------------- (a) 1X2 ----------------
    prem = odds.prematch_1x2(frame)
    sharp = odds.sharp_closing_1x2(frame)
    p_pre = odds.demargin(prem.odds.where(prem.available), "proportional").to_numpy()
    p_sharp = odds.demargin(sharp.odds.where(sharp.available), "proportional").to_numpy()
    model_p = frame[["p_home", "p_draw", "p_away"]].to_numpy()
    ok = np.isfinite(p_pre).all(axis=1) & np.isfinite(p_sharp).all(axis=1)

    naive = np.full((len(frame), 3), np.nan)
    for cutoff, group in frame.groupby("cutoff"):
        train = wf.training_frame_for(pool, cutoff, cfg, group["season"].iloc[0])
        rates = (np.array([np.mean(outcome(train) == k) for k in (0, 1, 2)])
                 if train is not None else np.array([1 / 3] * 3))
        naive[group.index.to_numpy()] = rates

    print("\n(a) 1X2 log loss per season (same subset: pre-match AND PSC available)")
    print(f"  {'season':<11}{'n':>5}{'model':>9}{'naive':>9}{'mkt pre':>9}{'PSC close':>11}")
    lm_all, lp_all, ls_all, ld_all = [], [], [], []
    for s in SEASONS:
        idx = np.where((season == s) & ok)[0]
        if len(idx) == 0:
            continue
        a = actual[idx]
        lm = row_ll(model_p[idx], a)
        lp = row_ll(p_pre[idx], a)
        ls = row_ll(p_sharp[idx], a)
        print(f"  {s:<11}{len(idx):>5}{lm.mean():>9.4f}{row_ll(naive[idx], a).mean():>9.4f}"
              f"{lp.mean():>9.4f}{ls.mean():>11.4f}")
        lm_all.append(lm); lp_all.append(lp); ls_all.append(ls); ld_all.append(days[idx])

    lm_all = np.concatenate(lm_all); lp_all = np.concatenate(lp_all)
    ls_all = np.concatenate(ls_all); ld_all = np.concatenate(ld_all)
    d_pre = boot(lm_all - lp_all, ld_all)
    d_sharp = boot(lm_all - ls_all, ld_all)
    print(f"  POOLED model {lm_all.mean():.4f} | market pre {lp_all.mean():.4f} | "
          f"PSC {ls_all.mean():.4f}")
    print(f"    model-market {d_pre[0]:+.4f} CI [{d_pre[1]:+.4f}, {d_pre[2]:+.4f}] "
          f"excludes 0: {d_pre[1] > 0 or d_pre[2] < 0}")
    print(f"    model-PSC    {d_sharp[0]:+.4f} CI [{d_sharp[1]:+.4f}, {d_sharp[2]:+.4f}] "
          f"excludes 0: {d_sharp[1] > 0 or d_sharp[2] < 0}")

    # ---------------- (b) blend ----------------
    print("\n(b) 1X2 blend (diagnostic)")
    bl_rows, ml_rows, bd_rows, bs = [], [], [], []
    for target in TARGETS:
        tr = ok & np.isin(season, [s for s in SEASONS if s < target])
        te = ok & (season == target)
        if tr.sum() == 0 or te.sum() == 0:
            continue
        a, b = fit_blend(p_pre[tr], model_p[tr], actual[tr])
        q = np.power(np.clip(p_pre[te], 1e-9, 1.0), a) * np.power(
            np.clip(model_p[te], 1e-9, 1.0), b)
        q = q / q.sum(axis=1, keepdims=True)
        bl_rows.append(row_ll(q, actual[te]))
        ml_rows.append(row_ll(p_pre[te], actual[te]))
        bd_rows.append(days[np.where(te)[0]])
        bs.append(b)
    if bl_rows:
        bl = np.concatenate(bl_rows); ml = np.concatenate(ml_rows); bd = np.concatenate(bd_rows)
        db = boot(bl - ml, bd)
        print(f"  per-season b: {[round(float(x), 3) for x in bs]}")
        print(f"  pooled blend {bl.mean():.4f} vs market {ml.mean():.4f} | "
              f"blend-market {db[0]:+.4f} CI [{db[1]:+.4f}, {db[2]:+.4f}] "
              f"excludes 0: {db[1] > 0 or db[2] < 0}")
    else:
        db = (float("nan"),) * 3

    # ---------------- (c) totals ----------------
    ou = odds.prematch_ou25(frame)
    p_over = odds.demargin(ou.odds.where(ou.available), "proportional")["over"].to_numpy()
    ok_ou = np.isfinite(p_over)
    print("\n(c) totals: tripwire (market vs constant) and decomposition")
    print(f"  {'season':<11}{'n':>5}{'const':>9}{'M0 mkt':>9}{'M0-const':>10}{'corr':>8}")
    tripwire = []
    for s in SEASONS:
        msk = (season == s) & ok_ou
        if msk.sum() == 0:
            continue
        y = over[msk]
        lc = m.log_loss(np.column_stack([np.full(len(y), 0.5)] * 2), y)
        l0 = m.log_loss(np.column_stack([1 - p_over[msk], p_over[msk]]), y)
        c = np.corrcoef(p_over[msk], y)[0, 1]
        flag = "TRIPWIRE" if l0 > lc else ""
        if l0 > lc:
            tripwire.append(s)
        print(f"  {s:<11}{int(msk.sum()):>5}{lc:>9.4f}{l0:>9.4f}{l0 - lc:>10.4f}{c:>8.4f}  {flag}")

    m0r, m1r, m2r, mdr = [], [], [], []
    for target in TARGETS:
        tr = ok_ou & np.isin(season, [s for s in SEASONS if s < target])
        te = ok_ou & (season == target)
        if tr.sum() == 0 or te.sum() == 0:
            continue
        b1 = fit_logistic(np.column_stack([np.ones(tr.sum()), logit(p_over[tr])]), over[tr].astype(float))
        b2 = fit_logistic(np.column_stack([np.ones(tr.sum()), logit(p_over[tr]),
                                           logit(frame["p_over25"].to_numpy()[tr])]), over[tr].astype(float))
        q1 = predict_logistic(np.column_stack([np.ones(te.sum()), logit(p_over[te])]), b1)
        q2 = predict_logistic(np.column_stack([np.ones(te.sum()), logit(p_over[te]),
                                               logit(frame["p_over25"].to_numpy()[te])]), b2)
        y = over[te]
        m0r.append(row_ll(np.column_stack([1 - p_over[te], p_over[te]]), y))
        m1r.append(row_ll(np.column_stack([1 - q1, q1]), y))
        m2r.append(row_ll(np.column_stack([1 - q2, q2]), y))
        mdr.append(days[np.where(te)[0]])
    if m0r:
        m0 = np.concatenate(m0r); m1 = np.concatenate(m1r); m2 = np.concatenate(m2r); md = np.concatenate(mdr)
        d10 = boot(m1 - m0, md); d21 = boot(m2 - m1, md)
        print(f"  pooled M0 {m0.mean():.4f} | M1 {m1.mean():.4f} | M2 {m2.mean():.4f}")
        print(f"    M1-M0 {d10[0]:+.4f} CI [{d10[1]:+.4f}, {d10[2]:+.4f}] "
              f"excludes 0: {d10[1] > 0 or d10[2] < 0}")
        print(f"    M2-M1 {d21[0]:+.4f} CI [{d21[1]:+.4f}, {d21[2]:+.4f}] "
              f"excludes 0: {d21[1] > 0 or d21[2] < 0}")
    else:
        d10 = d21 = (float("nan"),) * 3

    # ---------------- (d) combo calibration ----------------
    print("\n(d) combo calibration, ranked by log-loss gain vs naive then slope")
    fthg, ftag = frame["fthg"].to_numpy(), frame["ftag"].to_numpy()
    rows = []
    for col, (label, fn) in MARKETS.items():
        p = frame[col].to_numpy(dtype=float)
        y = np.asarray(fn(fthg, ftag)).astype(int)
        base = y.mean()
        ll = m.log_loss(np.column_stack([1 - p, p]), y)
        ll_naive = m.log_loss(np.column_stack([np.full(len(y), 1 - base), np.full(len(y), base)]), y)
        beta = fit_logistic(np.column_stack([np.ones(len(p)), logit(p)]), y.astype(float))
        rows.append({"market": label, "gain": ll_naive - ll, "slope": beta[1], "log_loss": ll})
    table = pd.DataFrame(rows).sort_values(["gain", "slope"], ascending=False)
    print(f"  {'market':<26}{'gain':>9}{'slope':>9}{'logloss':>10}")
    for r in table.head(6).itertuples(index=False):
        print(f"  {r.market:<26}{r.gain:>9.4f}{r.slope:>9.3f}{r.log_loss:>10.4f}")
    print("  ...")
    for r in table.tail(3).itertuples(index=False):
        print(f"  {r.market:<26}{r.gain:>9.4f}{r.slope:>9.3f}{r.log_loss:>10.4f}")
    calibrated = table[(table["gain"] > 0) & (table["slope"] > 0.3)]["market"].tolist()

    # ---------------- (e) payout check ----------------
    print("\n(e) payout check (model-probability bins)")
    bins_inspected = 0
    clearing = {}
    for src_name, (m1, mou) in (
        ("market avg", (prem, ou)),
        ("Pinnacle pre", (odds.pinnacle_1x2(frame), odds.pinnacle_ou25(frame))),
    ):
        clears = 0
        for name, p_model, price, out in (
            ("home", frame["p_home"].to_numpy(), m1.odds["home"].to_numpy(dtype=float), (fthg > ftag).astype(float)),
            ("draw", frame["p_draw"].to_numpy(), m1.odds["draw"].to_numpy(dtype=float), (fthg == ftag).astype(float)),
            ("away", frame["p_away"].to_numpy(), m1.odds["away"].to_numpy(dtype=float), (fthg < ftag).astype(float)),
            ("over", frame["p_over25"].to_numpy(), mou.odds["over"].to_numpy(dtype=float), (total > 2.5).astype(float)),
            ("under", (1 - frame["p_over25"]).to_numpy(), mou.odds["under"].to_numpy(dtype=float), (total < 2.5).astype(float)),
        ):
            valid = np.isfinite(p_model) & np.isfinite(price) & (price > 1.0)
            edges = np.linspace(0, 1, BINS + 1)
            idx = np.clip(np.digitize(p_model, edges[1:-1]), 0, BINS - 1)
            for b in range(BINS):
                mask = valid & (idx == b)
                n = int(mask.sum())
                if n == 0:
                    continue
                bins_inspected += 1
                hits = int(out[mask].sum())
                ci = wilson(hits, n)
                be = float((1.0 / price[mask]).mean())
                if ci[0] > be:
                    clears += 1
        clearing[src_name] = clears
        print(f"  {src_name:<14} bins clearing break-even: {clears}")
    print(f"  bins inspected: {bins_inspected}")

    results[slug] = {
        "model_minus_market": d_pre[0], "ci_low": d_pre[1], "ci_high": d_pre[2],
        "model_minus_psc": d_sharp[0],
        "blend_minus_market": db[0], "blend_ci_low": db[1], "blend_ci_high": db[2],
        "M0": m0.mean() if m0r else float("nan"),
        "M1_minus_M0": d10[0], "M2_minus_M1": d21[0],
        "tripwire_seasons": ",".join(tripwire) or "none",
        "calibrated_markets": len(calibrated),
        "bins_inspected": bins_inspected,
        "bins_clearing_market_avg": clearing.get("market avg", 0),
        "bins_clearing_pinnacle": clearing.get("Pinnacle pre", 0),
    }

    # pre-registered candidate reading
    beats_market = (d_pre[1] > 0 or d_pre[2] < 0) and d_pre[0] < 0
    blend_beats = (db[1] > 0 or db[2] < 0) and db[0] < 0
    pays = clearing.get("market avg", 0) > 0
    if beats_market or blend_beats:
        candidates.append((slug, "1X2", "model or blend beats market pre-match, CI excludes 0"))
    if pays:
        candidates.append((slug, "1X2/OU2.5", f"{clearing['market avg']} payout bins clear break-even at market-average prices"))
    if not (beats_market or blend_beats or pays):
        print(f"  -> no candidate for {slug}")

    ledger.log_evaluation(
        league=slug, market="1X2+OU2.5", selection="all",
        rule_config=f"TRANSFERRED CONFIG {cfg.config_id}",
        split="discovery:walk-forward", n_predictions=len(frame),
        log_loss=float(lm_all.mean()), brier="",
        benchmark_name="market_prematch", benchmark_log_loss=float(lp_all.mean()),
        n_bets="", roi="", mean_clv="",
        notes=(f"model-market {d_pre[0]:+.4f} CI [{d_pre[1]:+.4f},{d_pre[2]:+.4f}]; "
               f"blend-market {db[0]:+.4f}; M1-M0 {d10[0]:+.4f}; M2-M1 {d21[0]:+.4f}; "
               f"tripwire {','.join(tripwire) or 'none'}; bins {bins_inspected}"),
    )


def main() -> int:
    print("=" * 100)
    print("Step 3 — transferred config across ligue_2_t2, bundesliga_2, bundesliga_1")
    print("=" * 100)
    print("Config TRANSFERRED from League One, not re-tuned: "
          "xi=0.002, covid_mode=exclude_after, newcomer=newcomer_prior")
    ledger.append_note(
        "TRANSFERRED CONFIG: xi=0.002, covid_mode=exclude_after, newcomer=newcomer_prior "
        "applied unchanged to ligue_2_t2, bundesliga_2 and bundesliga_1 (not re-tuned)."
    )

    results: dict = {}
    candidates: list = []
    for slug in LEAGUES:
        evaluate_league(slug, results, candidates)

    print("\n" + "=" * 100)
    print("CROSS-LEAGUE TABLE")
    print("=" * 100)
    table = pd.DataFrame(results).T
    print(table.to_string(float_format=lambda v: f"{v:.4f}"))
    table.to_csv("reports/figures/cross_league.csv")

    print("\n" + "=" * 100)
    print("PRE-REGISTERED CANDIDATE READING")
    print("=" * 100)
    print("A league x market becomes a CONFIRMATION CANDIDATE only if")
    print("  (i) model or blend beats market pre-match with the CI excluding 0, or")
    print("  (ii) payout bins clear break-even at MARKET-AVERAGE prices with CI.")
    if candidates:
        for slug, market, why in candidates:
            print(f"  CANDIDATE: {slug} / {market} — {why}")
    else:
        print("  NO CANDIDATE in any league.")
    print("\nConfirmation seasons were NOT touched.")
    return 0


if __name__ == "__main__":
    sys.exit(main())