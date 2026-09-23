"""Step 5 — benchmarks with uncertainty, for the final config.

Final config: xi = 0.002, covid_mode = exclude_after, newcomer = newcomer_prior.

Per season (same subset for every contender):
  model | naive | market pre-match | SHARP close (PSC) | AvgC (where it exists)
De-margining reported both ways (proportional and power).

Paired bootstrap (2000 resamples, resampled by MATCHDAY) gives 95% CIs for the
model-minus-market log-loss difference, per season and pooled, for 1X2 and O/U 2.5.

No ROI, no bet simulation, no edge language.
"""

from __future__ import annotations

import sys

import numpy as np
import pandas as pd

from core import ledger, odds, walkforward as wf
from models import league_one_dixon_coles as m

SEASONS = ["2017-2018", "2018-2019", "2019-2020", "2020-2021", "2021-2022", "2022-2023"]
FINAL = wf.Config(xi=0.002, covid_mode="exclude_after", newcomer="newcomer_prior")

BOOTSTRAP_N = 2000
SEED = 20260923

ODDS_COLUMNS = [
    "avg_h", "avg_d", "avg_a", "avg_ch", "avg_cd", "avg_ca",
    "psch", "pscd", "psca", "b365_h", "b365_d", "b365_a",
    "b365_ch", "b365_cd", "b365_ca", "bb_av_h", "bb_av_d", "bb_av_a",
    "avg>2.5", "avg<2.5", "avg_c>2.5", "avg_c<2.5", "bb_av>2.5", "bb_av<2.5",
    "b365>2.5", "b365<2.5", "pc>2.5", "pc<2.5",
]


def outcome(frame: pd.DataFrame) -> np.ndarray:
    fthg, ftag = frame["fthg"].to_numpy(), frame["ftag"].to_numpy()
    out = np.full(len(frame), 1, dtype=int)
    out[fthg > ftag] = 0
    out[fthg < ftag] = 2
    return out


def row_log_loss(probs: np.ndarray, actual: np.ndarray) -> np.ndarray:
    return -np.log(np.clip(probs[np.arange(len(actual)), actual], 1e-15, 1.0))


def bootstrap_diff(
    loss_a: np.ndarray, loss_b: np.ndarray, days: np.ndarray, n: int = BOOTSTRAP_N, seed: int = SEED
) -> tuple[float, float, float]:
    """Paired bootstrap of mean(loss_a) - mean(loss_b), resampling matchdays."""
    rng = np.random.default_rng(seed)
    unique_days, inverse = np.unique(days, return_inverse=True)
    groups = [np.where(inverse == i)[0] for i in range(len(unique_days))]
    diff = loss_a - loss_b
    observed = float(diff.mean())
    draws = np.empty(n)
    for i in range(n):
        picks = rng.integers(0, len(groups), len(groups))
        idx = np.concatenate([groups[p] for p in picks])
        draws[i] = diff[idx].mean()
    return observed, float(np.percentile(draws, 2.5)), float(np.percentile(draws, 97.5))


def main() -> int:
    pool = wf.load_pool(FINAL.league)
    preds = wf.run(FINAL, SEASONS, pool=pool)
    raw = pool.reset_index().rename(columns={"index": "row", "id": "match_key"})
    frame = preds.merge(raw[["match_key"] + ODDS_COLUMNS], on="match_key", how="left")
    assert len(frame) == len(preds)

    actual = outcome(frame)
    days = frame["date"].to_numpy()

    print("=" * 96)
    print(f"Step 5 — benchmarks for the final config: {FINAL.config_id}")
    print("=" * 96)

    prem = odds.prematch_1x2(frame)
    sharp = odds.sharp_closing_1x2(frame)
    avgc = odds.avgc_closing_1x2(frame)
    pre_prop = odds.demargin(prem.odds.where(prem.available), "proportional")
    pre_pow = odds.demargin(prem.odds.where(prem.available), "power")
    sharp_prop = odds.demargin(sharp.odds.where(sharp.available), "proportional")
    avgc_prop = odds.demargin(avgc.odds.where(avgc.available), "proportional")

    print(f"pre-match  : {sorted(set(prem.source.dropna()))} ({int(prem.available.sum())}/{len(frame)})")
    print(f"SHARP (PSC): {sorted(set(sharp.source.dropna()))} ({int(sharp.available.sum())}/{len(frame)})")
    print(f"AvgC       : {sorted(set(avgc.source.dropna()))} ({int(avgc.available.sum())}/{len(frame)})")

    # naive per cutoff
    naive = np.full((len(frame), 3), np.nan)
    for cutoff, group in frame.groupby("cutoff"):
        train = wf.training_frame_for(pool, cutoff, FINAL, group["season"].iloc[0])
        rates = (
            np.array([np.mean(outcome(train) == k) for k in (0, 1, 2)])
            if train is not None
            else np.array([1 / 3, 1 / 3, 1 / 3])
        )
        naive[group.index.to_numpy()] = rates

    model_p = frame[["p_home", "p_draw", "p_away"]].to_numpy()
    loss_model = row_log_loss(model_p, actual)
    loss_naive = row_log_loss(naive, actual)

    print("\n--- 1X2 log loss / Brier per season (same subset = rows with PSC) ---")
    print(f"{'season':<10}{'n':>5}{'model':>9}{'naive':>9}{'mkt pre':>9}"
          f"{'SHARP PSC':>11}{'AvgC':>9}{'n_AvgC':>8}")
    per_season = []
    for season in SEASONS:
        idx = np.where((frame["season"] == season).to_numpy() & sharp.available.to_numpy())[0]
        a = actual[idx]
        row = {
            "season": season,
            "n": len(idx),
            "model": m.log_loss(model_p[idx], a),
            "naive": m.log_loss(naive[idx], a),
            "market_pre": m.log_loss(pre_prop.to_numpy()[idx], a),
        }
        avgc_idx = np.intersect1d(idx, np.where(avgc.available.to_numpy())[0])
        row["sharp_psc"] = m.log_loss(sharp_prop.to_numpy()[idx], a)
        row["avgc"] = m.log_loss(avgc_prop.to_numpy()[avgc_idx], actual[avgc_idx]) if len(avgc_idx) else float("nan")
        row["n_avgc"] = len(avgc_idx)
        row["model_brier"] = m.brier(model_p[idx], a)
        row["market_brier"] = m.brier(pre_prop.to_numpy()[idx], a)
        per_season.append(row)
        print(f"{season:<10}{len(idx):>5}{row['model']:>9.4f}{row['naive']:>9.4f}"
              f"{row['market_pre']:>9.4f}{row['sharp_psc']:>11.4f}{row['avgc']:>9.4f}{row['n_avgc']:>8}")
    table = pd.DataFrame(per_season)

    print("\n--- de-margin method sensitivity (1X2, pooled over PSC rows) ---")
    idx = np.where(sharp.available.to_numpy())[0]
    print(f"  pre-match : proportional {m.log_loss(pre_prop.to_numpy()[idx], actual[idx]):.5f} | "
          f"power {m.log_loss(pre_pow.to_numpy()[idx], actual[idx]):.5f}")
    print(f"  SHARP PSC : proportional {m.log_loss(sharp_prop.to_numpy()[idx], actual[idx]):.5f}")

    # ---------------- bootstrap CIs ----------------
    print(f"\n--- paired bootstrap ({BOOTSTRAP_N} resamples by matchday) ---")
    print(f"{'scope':<12}{'model-mkt_pre':>15}{'95% CI':>24}{'model-SHARP':>14}{'95% CI':>24}")
    pooled = {"model_pre": [], "model_sharp": []}
    for season in SEASONS:
        idx = np.where((frame["season"] == season).to_numpy() & sharp.available.to_numpy())[0]
        lm, lp = loss_model[idx], row_log_loss(pre_prop.to_numpy()[idx], actual[idx])
        ls = row_log_loss(sharp_prop.to_numpy()[idx], actual[idx])
        d1 = bootstrap_diff(lm, lp, days[idx])
        d2 = bootstrap_diff(lm, ls, days[idx])
        pooled["model_pre"].append((lm, lp, days[idx]))
        pooled["model_sharp"].append((lm, ls, days[idx]))
        print(f"{season:<12}{d1[0]:>15.4f}{f'[{d1[1]:.4f}, {d1[2]:.4f}]':>24}"
              f"{d2[0]:>14.4f}{f'[{d2[1]:.4f}, {d2[2]:.4f}]':>24}")

    lm_all = np.concatenate([x[0] for x in pooled["model_pre"]])
    lp_all = np.concatenate([x[1] for x in pooled["model_pre"]])
    ls_all = np.concatenate([x[2] for x in pooled["model_sharp"]])
    days_all = np.concatenate([x[2] for x in pooled["model_pre"]])
    ls_all = np.concatenate([x[1] for x in pooled["model_sharp"]])
    d1 = bootstrap_diff(lm_all, lp_all, days_all)
    d2 = bootstrap_diff(lm_all, ls_all, days_all)
    print(f"{'POOLED':<12}{d1[0]:>15.4f}{f'[{d1[1]:.4f}, {d1[2]:.4f}]':>24}"
          f"{d2[0]:>14.4f}{f'[{d2[1]:.4f}, {d2[2]:.4f}]':>24}")

    # O/U bootstrap
    ou = odds.prematch_ou25(frame)
    ou_mkt = odds.demargin(ou.odds.where(ou.available))
    has = ou.available.to_numpy()
    over = (frame["fthg"] + frame["ftag"] > 2.5).to_numpy().astype(int)
    p_model_ou = np.column_stack([1 - frame["p_over25"].to_numpy(), frame["p_over25"].to_numpy()])
    print(f"\n--- O/U 2.5, same rows with pre-match O/U odds ({int(has.sum())} rows) ---")
    lm_ou = row_log_loss(p_model_ou[has], over[has])
    lmkt_ou = row_log_loss(ou_mkt.to_numpy()[has], over[has])
    d = bootstrap_diff(lm_ou, lmkt_ou, days[has])
    print(f"  pooled model {lm_ou.mean():.4f} vs market {lmkt_ou.mean():.4f} "
          f"| diff {d[0]:.4f} [{d[1]:.4f}, {d[2]:.4f}]")

    table.to_csv("reports/figures/league_one_benchmark_final.csv", index=False)
    ledger.log_evaluation(
        league=FINAL.league,
        market="1X2",
        selection="home/draw/away",
        rule_config=f"FINAL BENCHMARK {FINAL.config_id}",
        split="discovery:all",
        n_predictions=len(lm_all),
        log_loss=float(lm_all.mean()),
        brier="",
        benchmark_name="market_prematch",
        benchmark_log_loss=float(lp_all.mean()),
        n_bets="",
        roi="",
        mean_clv="",
        notes=(
            f"pooled model-market diff {d1[0]:.4f} CI [{d1[1]:.4f},{d1[2]:.4f}]; "
            f"vs SHARP PSC diff {d2[0]:.4f} CI [{d2[1]:.4f},{d2[2]:.4f}]; "
            f"O/U diff {d[0]:.4f} CI [{d[1]:.4f},{d[2]:.4f}]"
        ),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())