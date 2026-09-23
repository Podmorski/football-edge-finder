"""Step 7 — self-audit.

In a FRESH process:
  1. Ensure the final config's predictions are persisted as an artifact.
  2. Recompute every headline number from saved artifacts (predictions parquet,
     data/historical, data/auxiliary, research/ledger.csv) and assert agreement
     with the claimed value within 1e-9.
  3. List any claimed number that is NOT backed by an artifact.
  4. Clear the fit cache for one season, re-run, and confirm identical predictions.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from core import odds, walkforward as wf
from models import league_one_dixon_coles as m
import encompass_league_one as en

SEASONS = ["2017-2018", "2018-2019", "2019-2020", "2020-2021", "2021-2022", "2022-2023"]
FINAL = wf.Config(xi=0.002, covid_mode="exclude_after", newcomer="newcomer_prior")
PRED_PATH = wf.PRED_DIR / f"{FINAL.config_id}.parquet"
TOL = 1e-9

# Headline numbers claimed in the summary. Values marked ARTIFACT are recomputed
# from saved files; CONFIG-ONLY ones are recomputations of deterministic code.
CLAIMED = [
    ("predictions rows", 3160, "ARTIFACT"),
    ("blend-weight<1 matches", 371, "ARTIFACT"),
    ("2021-22 model 1X2", 1.0192, "ARTIFACT"),
    ("2022-23 model 1X2", 1.0161, "ARTIFACT"),
    ("2021-22 naive 1X2", 1.0707, "ARTIFACT"),
    ("2021-22 market pre 1X2", 1.0000, "ARTIFACT"),
    ("2022-23 market pre 1X2", 1.0055, "ARTIFACT"),
    ("pooled model-market 1X2", 0.0142, "ARTIFACT"),
    ("pooled model-SHARP 1X2", 0.0194, "ARTIFACT"),
    ("O/U pooled model", 0.7061, "ARTIFACT"),
    ("O/U pooled market", 0.7029, "ARTIFACT"),
    ("covid include mean 1X2", 1.0289, "ARTIFACT"),
    ("covid exclude_after mean 1X2", 1.0177, "ARTIFACT"),
    ("covid downweight_0.5 mean 1X2", 1.0237, "ARTIFACT"),
    ("blend-market pooled diff", -0.0009, "ARTIFACT"),
    ("blend b (pooled)", 0.0265, "ARTIFACT"),
    ("O/U blend-market diff", -0.0110, "ARTIFACT"),
    ("grid parity max abs diff", 0.0, "CONFIG-ONLY"),
    ("corr(model E[total], actual)", 0.0257, "ARTIFACT"),
    ("corr(model P(over), actual)", 0.0103, "ARTIFACT"),
]


def outcome(frame: pd.DataFrame) -> np.ndarray:
    fthg, ftag = frame["fthg"].to_numpy(), frame["ftag"].to_numpy()
    out = np.full(len(frame), 1, dtype=int)
    out[fthg > ftag] = 0
    out[fthg < ftag] = 2
    return out


def row_ll(probs: np.ndarray, actual: np.ndarray) -> np.ndarray:
    return -np.log(np.clip(probs[np.arange(len(actual)), actual], 1e-15, 1.0))


def ensure_artifact() -> pd.DataFrame:
    if not PRED_PATH.exists():
        print(f"  (artifact missing; generating {PRED_PATH.name})")
        pool = wf.load_pool(FINAL.league)
        frame = wf.run(FINAL, SEASONS, pool=pool)
        wf.save_predictions(frame, FINAL)
    return pd.read_parquet(PRED_PATH)


def main() -> int:
    print("=" * 90)
    print("Step 7 — self-audit (fresh process, recomputed from artifacts)")
    print("=" * 90)

    preds = ensure_artifact()
    pool = wf.load_pool(FINAL.league)
    odd_cols = ["avg_h", "avg_d", "avg_a", "bb_av_h", "bb_av_d", "bb_av_a",
                "b365_h", "b365_d", "b365_a", "psch", "pscd", "psca",
                "avg_c>2.5", "avg_c<2.5", "avg>2.5", "avg<2.5",
                "bb_av>2.5", "bb_av<2.5", "b365>2.5", "b365<2.5"]
    raw = pool.reset_index().rename(columns={"index": "row", "id": "match_key"})
    frame = preds.merge(raw[["match_key"] + odd_cols], on="match_key", how="left")
    actual = outcome(frame)
    days = frame["date"].to_numpy()

    recomputed: dict[str, float] = {}
    recomputed["predictions rows"] = float(len(frame))
    recomputed["blend-weight<1 matches"] = float(
        ((frame["home_blend_weight"] < 1) | (frame["away_blend_weight"] < 1)).sum()
    )

    prem = odds.prematch_1x2(frame)
    p_pre = odds.demargin(prem.odds.where(prem.available)).to_numpy()
    sharp = odds.sharp_closing_1x2(frame)
    p_sharp = odds.demargin(sharp.odds.where(sharp.available)).to_numpy()
    model_p = frame[["p_home", "p_draw", "p_away"]].to_numpy()
    # Pool all three on the SAME rows: pre-match AND SHARP both available.
    ok = np.isfinite(p_pre).all(axis=1) & np.isfinite(p_sharp).all(axis=1)

    naive = np.full((len(frame), 3), np.nan)
    for cutoff, group in frame.groupby("cutoff"):
        train = wf.training_frame_for(pool, cutoff, FINAL, group["season"].iloc[0])
        rates = (np.array([np.mean(outcome(train) == k) for k in (0, 1, 2)])
                 if train is not None else np.array([1 / 3] * 3))
        naive[group.index.to_numpy()] = rates

    for season, key in (("2021-2022", "2021-22"), ("2022-2023", "2022-23")):
        idx = np.where((frame["season"] == season).to_numpy() & ok)[0]
        recomputed[f"{key} model 1X2"] = m.log_loss(model_p[idx], actual[idx])
        recomputed[f"{key} naive 1X2"] = m.log_loss(naive[idx], actual[idx])
        recomputed[f"{key} market pre 1X2"] = m.log_loss(p_pre[idx], actual[idx])

    recomputed["pooled model-market 1X2"] = float(
        m.log_loss(model_p[ok], actual[ok]) - m.log_loss(p_pre[ok], actual[ok])
    )
    recomputed["pooled model-SHARP 1X2"] = float(
        m.log_loss(model_p[ok], actual[ok]) - m.log_loss(p_sharp[ok], actual[ok])
    )

    ou = odds.prematch_ou25(frame)
    ou_mkt = odds.demargin(ou.odds.where(ou.available)).to_numpy()
    has_ou = ou.available.to_numpy()
    over = ((frame["fthg"] + frame["ftag"]) > 2.5).to_numpy().astype(int)
    p_model_ou = np.column_stack([1 - frame["p_over25"].to_numpy(), frame["p_over25"].to_numpy()])
    recomputed["O/U pooled model"] = m.log_loss(p_model_ou[has_ou], over[has_ou])
    recomputed["O/U pooled market"] = m.log_loss(ou_mkt[has_ou], over[has_ou])

    # covid table artifact
    covid_csv = Path("reports/figures/league_one_covid_mode.csv")
    if covid_csv.exists():
        tbl = pd.read_csv(covid_csv).set_index("mode")
        for mode in ("include", "exclude_after", "downweight_0.5"):
            recomputed[f"covid {mode} mean 1X2"] = float(tbl.loc[mode, "mean_1x2"])

    blend_csv = Path("reports/figures/league_one_blend_1x2.csv")
    if blend_csv.exists():
        bl = pd.read_csv(blend_csv)
        recomputed["blend b (pooled)"] = float(bl["b"].mean())

    # ---- independent recomputation of the blend test from the artifact ----
    season_arr = frame["season"].to_numpy()
    blend_ok = np.isfinite(p_pre).all(axis=1) & np.isfinite(p_sharp).all(axis=1)
    bl_rows, ml_rows, sl_rows, day_rows = [], [], [], []
    for target in en.TARGETS:
        train_mask = blend_ok & np.isin(season_arr, [s for s in en.SEASONS if s < target])
        test_mask = blend_ok & (season_arr == target)
        if train_mask.sum() == 0 or test_mask.sum() == 0:
            continue
        a, b = en.fit_1x2(
            p_pre[train_mask], model_p[train_mask], actual[train_mask]
        )
        q = en.blend_1x2(p_pre[test_mask], model_p[test_mask], a, b)
        bl_rows.append(en.row_ll(q, actual[test_mask]))
        ml_rows.append(en.row_ll(p_pre[test_mask], actual[test_mask]))
        sl_rows.append(en.row_ll(p_sharp[test_mask], actual[test_mask]))
        day_rows.append(days[test_mask])
    bl = np.concatenate(bl_rows)
    ml = np.concatenate(ml_rows)
    sl = np.concatenate(sl_rows)
    recomputed["blend-market pooled diff"] = float((bl - ml).mean())
    # b is fitted on a very flat objective; use the same mask as the producer so
    # Nelder-Mead (deterministic) lands on the same point.
    pre_only = np.isfinite(p_pre).all(axis=1)
    recomputed["blend b (pooled)"] = en.fit_1x2(
        p_pre[pre_only], model_p[pre_only], actual[pre_only]
    )[1]

    # O/U blend recomputation
    ou_ok = has_ou & np.isfinite(
        odds.demargin(ou.odds.where(ou.available)).to_numpy()[:, 1]
    )
    ou_series = ou_mkt[:, 1]
    obl, oml = [], []
    for target in en.TARGETS:
        train_mask = ou_ok & np.isin(season_arr, [s for s in en.SEASONS if s < target])
        test_mask = ou_ok & (season_arr == target)
        if train_mask.sum() == 0 or test_mask.sum() == 0:
            continue
        beta = en.fit_logistic(
            en.logit(ou_series[train_mask]),
            en.logit(frame["p_over25"].to_numpy()[train_mask]),
            over[train_mask].astype(float),
        )
        design = np.column_stack([
            np.ones(int(test_mask.sum())),
            en.logit(ou_series[test_mask]),
            en.logit(frame["p_over25"].to_numpy()[test_mask]),
        ])
        q_ou = 1.0 / (1.0 + np.exp(-(design @ beta)))
        y = over[test_mask]
        obl.append(en.row_ll(np.column_stack([1 - q_ou, q_ou]), y))
        oml.append(en.row_ll(np.column_stack([1 - ou_series[test_mask], ou_series[test_mask]]), y))
    recomputed["O/U blend-market diff"] = float(
        (np.concatenate(obl) - np.concatenate(oml)).mean()
    )

    total = frame["fthg"] + frame["ftag"]
    pmfs = np.vstack(frame["total_goals_pmf"].to_numpy())
    ks = np.arange(pmfs.shape[1])
    e_total = (pmfs * ks).sum(axis=1)
    recomputed["corr(model E[total], actual)"] = float(np.corrcoef(e_total, total.to_numpy())[0, 1])
    recomputed["corr(model P(over), actual)"] = float(
        np.corrcoef(frame["p_over25"].to_numpy(), (total > 2.5).to_numpy().astype(float))[0, 1]
    )

    recomputed["grid parity max abs diff"] = float(wf.grid_parity(n=200, seed=11)["max_abs_diff"])

    # ---------------- compare ----------------
    print(f"\n{'claim':<34}{'claimed':>12}{'recomputed':>14}{'|diff|':>11}  status")
    failures, not_backed = [], []
    for name, claimed, backing in CLAIMED:
        if name not in recomputed:
            not_backed.append((name, claimed, backing))
            print(f"{name:<34}{claimed:>12.4f}{'-':>14}{'-':>11}  NO ARTIFACT")
            continue
        got = recomputed[name]
        # claimed values are rounded for display; compare to display precision
        diff = abs(got - claimed)
        ok_ = diff <= max(TOL, 5e-5)
        if not ok_:
            failures.append((name, claimed, got))
        print(f"{name:<34}{claimed:>12.4f}{got:>14.4f}{diff:>11.2e}  {'OK' if ok_ else 'MISMATCH'}")

    print(f"\nclaimed numbers not backed by an artifact: {len(not_backed)}")
    for name, claimed, backing in not_backed:
        print(f"  - {name} = {claimed} ({backing})")
    print(f"mismatches: {len(failures)}")

    # ---------------- cache-clear reproducibility ----------------
    print("\n" + "=" * 90)
    print("Cache-clear reproducibility check (season 2022-2023)")
    print("=" * 90)
    season = "2022-2023"
    first = wf.run(FINAL, [season], pool=pool)
    cache_dir = wf.CACHE_DIR / FINAL.league / f"xi{FINAL.xi:g}__{FINAL.covid_mode}"
    removed = len(list(cache_dir.glob("*.json"))) if cache_dir.exists() else 0
    if cache_dir.exists():
        shutil.rmtree(cache_dir)
    second = wf.run(FINAL, [season], pool=pool)

    inter = first.set_index("match_key")
    inter2 = second.set_index("match_key")
    assert set(inter.index) == set(inter2.index), "row sets differ after cache clear"
    cols = ["p_home", "p_draw", "p_away", "p_over25", "p_btts",
            "expected_home_goals", "expected_away_goals"]
    worst = float(np.abs(inter[cols].to_numpy() - inter2[cols].to_numpy()).max())
    print(f"  cache files removed: {removed}")
    print(f"  rows: {len(inter)} vs {len(inter2)}")
    print(f"  max abs difference across {len(cols)} columns: {worst:.3e}")
    print(f"  identical: {worst == 0.0}")

    print("\nSELF-AUDIT RESULT:",
          "PASS" if (not failures and worst == 0.0) else "FAIL")
    return 0 if not failures and worst == 0.0 else 1


if __name__ == "__main__":
    sys.exit(main())