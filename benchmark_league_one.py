"""Benchmark the best walk-forward config against naive and the market.

Same match subset for every contender. Metrics: 1X2 log loss + Brier, and
O/U 2.5 log loss against the market where available. Also 10-bin reliability
for P(home) and P(over 2.5) pooled over validation seasons.

No ROI, no bet simulation, no edge language.

STOP RULE: if the walk-forward model does not beat naive on the validation
seasons, stop and report — no further tweaking.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

from core import ledger, odds, walkforward as wf
from models import league_one_dixon_coles as m

ALL_SEASONS = ["2017-2018", "2018-2019", "2019-2020", "2020-2021", "2021-2022", "2022-2023"]
TUNE_SEASONS = ["2017-2018", "2018-2019", "2020-2021"]
VALIDATION_SEASONS = ["2021-2022", "2022-2023"]

# Stage-A winner with the Stage-B winning newcomer policy.
BEST = wf.Config(xi=0.002, drop_2020_21=False, newcomer="newcomer_prior")

REPORT_PATH = Path("reports/phase2_step5_league_one.md")


def outcome_index(frame: pd.DataFrame) -> np.ndarray:
    fthg, ftag = frame["fthg"].to_numpy(), frame["ftag"].to_numpy()
    out = np.full(len(frame), 1, dtype=int)
    out[fthg > ftag] = 0
    out[fthg < ftag] = 2
    return out


def metrics(probs: np.ndarray, actual: np.ndarray) -> dict[str, float]:
    return {
        "log_loss": m.log_loss(probs, actual),
        "brier": m.brier(probs, actual),
        "accuracy": float((probs.argmax(axis=1) == actual).mean()),
    }


def naive_per_cutoff(pool: pd.DataFrame, frame: pd.DataFrame, config: wf.Config) -> np.ndarray:
    """Training base rates available at each row's own cutoff."""
    out = np.full((len(frame), 3), np.nan)
    for cutoff, group in frame.groupby("cutoff"):
        train = wf.training_frame_for(pool, cutoff, config)
        if train is None:
            rates = np.array([1 / 3, 1 / 3, 1 / 3])
        else:
            actual = outcome_index(train)
            rates = np.array([np.mean(actual == k) for k in (0, 1, 2)])
        out[group.index.to_numpy()] = rates
    return out


def build_frame() -> pd.DataFrame:
    pool = wf.load_pool(BEST.league)
    preds = wf.run(BEST, ALL_SEASONS, pool=pool)

    raw = pool.reset_index().rename(columns={"index": "row", "id": "match_key"})
    merged = preds.merge(
        raw[["match_key", "avg_h", "avg_d", "avg_a", "avg_ch", "avg_cd", "avg_ca",
             "b365_h", "b365_d", "b365_a", "b365_ch", "b365_cd", "b365_ca",
             "bb_av_h", "bb_av_d", "bb_av_a", "psch", "pscd", "psca",
             "avg>2.5", "avg<2.5", "avg_c>2.5", "avg_c<2.5",
             "bb_av>2.5", "bb_av<2.5", "b365>2.5", "b365<2.5"]],
        on="match_key", how="left", suffixes=("", "_raw"),
    )
    assert len(merged) == len(preds)
    return merged


def fmt(value, width: int) -> str:
    return " " * (width - 1) + "-" if value is None else f"{value:>{width}.3f}"


def print_reliability(model_table, market_table) -> None:
    print(f"    {'bin':<10}{'n':>5}{'model_pred':>12}{'mkt_pred':>10}{'observed':>10}")
    for (bucket, n, pred, obs), (_, mn, mpred, mobs) in zip(model_table, market_table):
        if pred is None and mpred is None:
            print(f"    {bucket:<10}{0:>5}{fmt(None, 12)}{fmt(None, 10)}{fmt(None, 10)}")
            continue
        row_n = n if n else mn
        observed = obs if obs is not None else mobs
        print(
            f"    {bucket:<10}{row_n:>5}{fmt(pred, 12)}{fmt(mpred, 10)}"
            f"{fmt(observed, 10)}"
        )


def main() -> int:
    frame = build_frame()
    print("=" * 82)
    print(f"League One benchmark — best config: {BEST.config_id}")
    print("=" * 82)

    pre = odds.prematch_1x2(frame)
    clo = odds.closing_1x2(frame)
    probs_pre = odds.demargin(pre.odds.where(pre.available))
    probs_clo = odds.demargin(clo.odds.where(clo.available))
    naive = naive_per_cutoff(wf.load_pool(BEST.league), frame, BEST)
    actual = outcome_index(frame)

    print(f"pre-match source(s): {sorted(set(pre.source.dropna()))} "
          f"({int(pre.available.sum())}/{len(frame)})")
    print(f"closing source(s)  : {sorted(set(clo.source.dropna()))} "
          f"({int(clo.available.sum())}/{len(frame)})")
    print(f"pre-match margin   : {odds.booksum_margin(pre.odds[pre.available]).mean():.4f}")
    print(f"closing margin     : {odds.booksum_margin(clo.odds[clo.available]).mean():.4f}")

    rows = []
    for season in ALL_SEASONS:
        mask = (frame["season"] == season).to_numpy()
        subset = frame[mask]
        a = actual[mask]
        model_p = subset[["p_home", "p_draw", "p_away"]].to_numpy()

        has_pre = pre.available.to_numpy()
        common = mask & has_pre
        model_c = frame.loc[common, ["p_home", "p_draw", "p_away"]].to_numpy()
        naive_c = naive[common]
        pre_c = probs_pre[common].to_numpy()
        a_c = actual[common]

        row = {
            "season": season,
            "n": int(common.sum()),
            "model": m.log_loss(model_c, a_c),
            "naive": m.log_loss(naive_c, a_c),
            "market_pre": m.log_loss(pre_c, a_c),
            "model_minus_market": m.log_loss(model_c, a_c) - m.log_loss(pre_c, a_c),
        }
        has_clo = mask & clo.available.to_numpy()
        if has_clo.any():
            row["n_closing"] = int(has_clo.sum())
            row["market_closing"] = m.log_loss(probs_clo[has_clo].to_numpy(), actual[has_clo])
            row["model_closing"] = m.log_loss(
                frame.loc[has_clo, ["p_home", "p_draw", "p_away"]].to_numpy(), actual[has_clo]
            )
        rows.append(row)

    table = pd.DataFrame(rows)
    print("\n--- 1X2 log loss per season (same pre-match subset) ---")
    print(table.to_string(index=False, float_format=lambda v: f"{v:.4f}"))

    brier_rows = []
    for season in ALL_SEASONS:
        common = (frame["season"] == season).to_numpy() & pre.available.to_numpy()
        a_c = actual[common]
        brier_rows.append({
            "season": season,
            "model_brier": m.brier(frame.loc[common, ["p_home", "p_draw", "p_away"]].to_numpy(), a_c),
            "naive_brier": m.brier(naive[common], a_c),
            "market_brier": m.brier(probs_pre[common].to_numpy(), a_c),
        })
    brier = pd.DataFrame(brier_rows)
    print("\n--- 1X2 Brier per season ---")
    print(brier.to_string(index=False, float_format=lambda v: f"{v:.4f}"))

    # ---------------- O/U 2.5 vs market ----------------
    ou_pre = odds.prematch_ou25(frame)
    ou_rows = []
    for season in ALL_SEASONS:
        mask = (frame["season"] == season).to_numpy() & ou_pre.available.to_numpy()
        if not mask.any():
            continue
        over = ((frame.loc[mask, "fthg"] + frame.loc[mask, "ftag"]) > 2.5).to_numpy().astype(int)
        p_model = frame.loc[mask, "p_over25"].to_numpy()
        mkt = odds.demargin(ou_pre.odds.where(ou_pre.available))[mask].to_numpy()
        ou_rows.append({
            "season": season,
            "n": int(mask.sum()),
            "model": m.log_loss(np.column_stack([1 - p_model, p_model]), over),
            "market": m.log_loss(mkt, over),
            "source": "+".join(sorted(set(ou_pre.source[mask].dropna()))),
        })
    ou = pd.DataFrame(ou_rows)
    print("\n--- O/U 2.5 log loss vs market (pre-match) ---")
    print(ou.to_string(index=False, float_format=lambda v: f"{v:.4f}"))

    # ---------------- reliability (validation, pooled) ----------------
    val_mask = frame["season"].isin(VALIDATION_SEASONS).to_numpy()
    val_pre = val_mask & pre.available.to_numpy()
    print("\n--- 10-bin reliability, pooled over validation seasons "
          f"({VALIDATION_SEASONS}) ---")
    model_ph = frame.loc[val_pre, "p_home"].to_numpy()
    mkt_ph = probs_pre.loc[val_pre, "home"].to_numpy()
    a_val = actual[val_pre]
    print("  P(home):")
    print_reliability(
        m.reliability_table(model_ph, a_val, bins=10),
        m.reliability_table(mkt_ph, a_val, bins=10),
    )

    over_val = ((frame.loc[val_mask, "fthg"] + frame.loc[val_mask, "ftag"]) > 2.5).to_numpy().astype(int)
    model_po = frame.loc[val_mask, "p_over25"].to_numpy()
    mkt_ou_val = odds.demargin(ou_pre.odds.where(ou_pre.available))
    mkt_po = mkt_ou_val[val_mask].to_numpy()[:, 1]
    valid = np.isfinite(mkt_po)
    print("  P(over 2.5) [market available rows only]:")
    print_reliability(
        m.reliability_table(model_po[valid], over_val[valid], bins=10),
        m.reliability_table(mkt_po[valid], over_val[valid], bins=10),
    )

    # ---------------- STOP RULE ----------------
    val = table[table["season"].isin(VALIDATION_SEASONS)]
    beats = bool((val["model"] < val["naive"]).all())
    print("\n" + "=" * 82)
    print("STOP RULE — model vs naive on validation seasons")
    for row in val.itertuples(index=False):
        verdict = "BEATS" if row.model < row.naive else "LOSES TO"
        print(f"  {row.season}: model {row.model:.4f} {verdict} naive {row.naive:.4f}")
    print(f"model beats naive on every validation season: {beats}")
    if not beats:
        print("!! STOP RULE TRIGGERED — stopping, no further tweaking")
    else:
        print("model beats naive out-of-sample on both validation seasons")

    table.to_csv("reports/figures/league_one_benchmark_1x2.csv", index=False)
    ou.to_csv("reports/figures/league_one_benchmark_ou25.csv", index=False)

    ledger.log_evaluation(
        league=BEST.league,
        market="1X2",
        selection="home/draw/away",
        rule_config=f"BENCHMARK {BEST.config_id}",
        split="discovery:validation",
        n_predictions=int(val["n"].sum()),
        log_loss=float((val["model"] * val["n"]).sum() / val["n"].sum()),
        brier="",
        benchmark_name="market_prematch + naive",
        benchmark_log_loss=float((val["market_pre"] * val["n"]).sum() / val["n"].sum()),
        n_bets="",
        roi="",
        mean_clv="",
        notes=(
            "beats naive on validation: "
            f"{beats}; mean model-minus-market gap "
            f"{float(((val['model'] - val['market_pre']) * val['n']).sum() / val['n'].sum()):.4f}"
        ),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())