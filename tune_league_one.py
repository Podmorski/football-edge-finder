"""League One tuning: Stage A (xi x COVID) and Stage B (newcomer policy).

Walk-forward, discovery seasons only. Confirmation is never loaded.

Stage A  newcomer=league_avg, grid xi x {include, drop_2020_21}
         tune on 2017-18, 2018-19, 2020-21 by 1X2 log loss
         validation 2021-22, 2022-23; 2019-20 reported but not selected on
Stage B  at the Stage-A winner, compare the three newcomer policies

Every config x season is appended to the ledger. No ROI, no bet simulation.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from core import ledger, walkforward as wf
from models import league_one_dixon_coles as m

TUNE_SEASONS = ["2017-2018", "2018-2019", "2020-2021"]
VALIDATION_SEASONS = ["2021-2022", "2022-2023"]
REPORT_ONLY_SEASONS = ["2019-2020"]
ALL_SEASONS = TUNE_SEASONS + REPORT_ONLY_SEASONS + VALIDATION_SEASONS

XI_GRID = [0.0005, 0.001, 0.0015, 0.002, 0.003, 0.005]
COVID_OPTIONS = [False, True]
NEWCOMER_POLICIES = ["exclude", "league_avg", "newcomer_prior"]

FIGURES_DIR = Path("reports/figures")


def outcome_index(frame: pd.DataFrame) -> np.ndarray:
    fthg, ftag = frame["fthg"].to_numpy(), frame["ftag"].to_numpy()
    out = np.full(len(frame), 1, dtype=int)
    out[fthg > ftag] = 0
    out[fthg < ftag] = 2
    return out


def metrics(frame: pd.DataFrame) -> dict[str, float]:
    probs = frame[["p_home", "p_draw", "p_away"]].to_numpy()
    actual = outcome_index(frame)
    over = (frame["fthg"] + frame["ftag"] > 2.5).to_numpy().astype(int)
    p_over = frame["p_over25"].to_numpy()
    p_ou = np.column_stack([1.0 - p_over, p_over])
    return {
        "n": len(frame),
        "log_loss": m.log_loss(probs, actual),
        "brier": m.brier(probs, actual),
        "log_loss_ou25": m.log_loss(p_ou, over),
        "p_home_mean": float(frame["p_home"].mean()),
        "home_win_rate": float((actual == 0).mean()),
    }


def run_config(config: wf.Config, pool: pd.DataFrame) -> pd.DataFrame:
    frame = wf.run(config, ALL_SEASONS, pool=pool)
    if not frame.empty:
        wf.save_predictions(frame, config)
    return frame


def log_config(
    config: wf.Config, frame: pd.DataFrame, tag: str
) -> None:
    """Append one ledger row per season for this config."""
    for season in ALL_SEASONS:
        sub = frame[frame["season"] == season]
        if sub.empty:
            continue
        mm = metrics(sub)
        if season in TUNE_SEASONS:
            split = f"discovery:tune:{season}"
        elif season in VALIDATION_SEASONS:
            split = f"discovery:validation:{season}"
        else:
            split = f"discovery:report_only:{season}"
        ledger.log_evaluation(
            league=config.league,
            market="1X2",
            selection="home/draw/away",
            rule_config=f"{tag} xi={config.xi:g} covid={'drop21' if config.drop_2020_21 else 'incl'} nw={config.newcomer}",
            split=split,
            n_predictions=mm["n"],
            log_loss=round(mm["log_loss"], 6),
            brier=round(mm["brier"], 6),
            benchmark_name="",
            benchmark_log_loss="",
            n_bets="",
            roi="",
            mean_clv="",
            notes=f"walk-forward; OU2.5 log loss={mm['log_loss_ou25']:.6f}",
        )


def weight_table(frame: pd.DataFrame, season: str) -> dict:
    return metrics(frame[frame["season"] == season])


def main() -> int:
    print("=" * 80)
    print("League One tuning — walk-forward, discovery only (confirmation locked)")
    print("=" * 80)

    pool = wf.load_pool("league_one_t3")
    print(f"pool: {len(pool)} matches, seasons {pool['season'].min()}..{pool['season'].max()}")

    # ---------------- Stage A ----------------
    print("\n" + "=" * 80)
    print("STAGE A — xi x COVID  (newcomer=league_avg, no exclusions)")
    print("=" * 80)

    stage_a_rows = []
    frames: dict[tuple[float, bool], pd.DataFrame] = {}
    t0 = time.perf_counter()

    for covid in COVID_OPTIONS:
        for xi in XI_GRID:
            config = wf.Config(xi=xi, drop_2020_21=covid, newcomer="league_avg")
            started = time.perf_counter()
            frame = run_config(config, pool)
            frames[(xi, covid)] = frame
            elapsed = time.perf_counter() - started

            tune = [weight_table(frame, s)["log_loss"] for s in TUNE_SEASONS]
            val = [weight_table(frame, s)["log_loss"] for s in VALIDATION_SEASONS]
            rep = weight_table(frame, REPORT_ONLY_SEASONS[0])["log_loss"]
            tune_ou = [weight_table(frame, s)["log_loss_ou25"] for s in TUNE_SEASONS]
            row = {
                "xi": xi,
                "covid": "drop 2020-21" if covid else "include",
                "tune_1x2": float(np.mean(tune)),
                "tune_ou25": float(np.mean(tune_ou)),
                "val_1x2": float(np.mean(val)) if val else float("nan"),
                "report_2019_20": rep,
                "n_tune": int(sum(weight_table(frame, s)["n"] for s in TUNE_SEASONS)),
                "seconds": elapsed,
            }
            stage_a_rows.append(row)
            log_config(config, frame, "stageA")
            print(
                f"  xi={xi:<7g} covid={row['covid']:<13} "
                f"tune={row['tune_1x2']:.4f}  val={row['val_1x2']:.4f}  "
                f"2019-20={row['report_2019_20']:.4f}  ou25={row['tune_ou25']:.4f} "
                f"({elapsed:.1f}s)"
            )

    stage_a = pd.DataFrame(stage_a_rows).sort_values("tune_1x2").reset_index(drop=True)
    print(f"\nStage A total: {time.perf_counter() - t0:.1f}s")

    print("\n--- Stage A table sorted by TUNE 1X2 log loss ---")
    print(stage_a.to_string(index=False))

    best = stage_a.iloc[0]
    winner_covid = best["covid"] == "drop 2020-21"
    winner = wf.Config(xi=float(best["xi"]), drop_2020_21=bool(winner_covid), newcomer="league_avg")
    print(
        f"\nStage A winner: xi={winner.xi:g}, covid={best['covid']} "
        f"(tune 1X2 {best['tune_1x2']:.4f}, validation {best['val_1x2']:.4f})"
    )
    winner_frame = frames[(winner.xi, winner.drop_2020_21)]

    # ---------------- Stage B ----------------
    print("\n" + "=" * 80)
    print("STAGE B — newcomer policy at the Stage-A winner")
    print("=" * 80)

    stage_b_rows = []
    policy_frames: dict[str, pd.DataFrame] = {}
    for policy in NEWCOMER_POLICIES:
        config = wf.Config(xi=winner.xi, drop_2020_21=winner.drop_2020_21, newcomer=policy)
        frame = run_config(config, pool)
        policy_frames[policy] = frame

        newcomer_flags = frame["home_newcomer"] | frame["away_newcomer"]
        newcomer_rows = frame[newcomer_flags]

        pooled = metrics(frame)
        stage_b_rows.append(
            {
                "policy": policy,
                "predicted": len(frame),
                "newcomer_matches": int(newcomer_flags.sum()),
                "pooled_1x2": pooled["log_loss"],
                "pooled_ou25": pooled["log_loss_ou25"],
                "newcomer_1x2": (
                    metrics(newcomer_rows)["log_loss"] if len(newcomer_rows) else float("nan")
                ),
            }
        )
        log_config(config, frame, "stageB")
        print(
            f"  {policy:<15} predicted={len(frame):<5} newcomer_matches={int(newcomer_flags.sum()):<5} "
            f"pooled_1x2={pooled['log_loss']:.4f}  pooled_ou25={pooled['log_loss_ou25']:.4f}"
        )

    stage_b = pd.DataFrame(stage_b_rows)
    print("\n--- Stage B table ---")
    print(stage_b.to_string(index=False))

    # fair comparison on the match subset every policy can predict
    print("\n--- Stage B: same-subset comparison (matches no policy excludes) ---")
    common_keys = None
    for policy, frame in policy_frames.items():
        keys = set(frame["match_key"])
        common_keys = keys if common_keys is None else (common_keys & keys)
    for policy, frame in policy_frames.items():
        sub = frame[frame["match_key"].isin(common_keys)]
        mm = metrics(sub)
        print(f"  {policy:<15} n={len(sub):<5} 1X2={mm['log_loss']:.4f} ou25={mm['log_loss_ou25']:.4f}")

    # ---------------- newcomer priors + home advantage ----------------
    print("\n--- newcomer priors per target season (at that season's first cutoff) ---")
    for season in ALL_SEASONS:
        sub = winner_frame[winner_frame["season"] == season]
        if sub.empty:
            continue
        cutoff = sub["cutoff"].min()
        train = wf.training_frame_for(pool, cutoff, winner)
        if train is None:
            continue
        params = wf.fit_at(winner, train, cutoff)
        priors = wf.newcomer_priors(pool, params, cutoff)
        print(
            f"  {season} (cutoff {cutoff.date()}): "
            f"league_avg=({priors['league_avg'][0]:.3f}, {priors['league_avg'][1]:.3f})  "
            f"promoted_in=({priors['promoted_in'][0]:.3f}, {priors['promoted_in'][1]:.3f}) "
            f"[n={priors['n_promoted_in']}]  "
            f"relegated_in=({priors['relegated_in'][0]:.3f}, {priors['relegated_in'][1]:.3f}) "
            f"[n={priors['n_relegated_in']}]"
        )

    # home advantage over time (from the winner's refits)
    print("\n--- home advantage across refits (Stage-A winner) ---")
    trend = (
        winner_frame.groupby("cutoff")[["home_advantage", "rho"]]
        .first()
        .reset_index()
        .sort_values("cutoff")
    )
    print(f"  refits: {len(trend)} | home_advantage min/mean/max: "
          f"{trend['home_advantage'].min():.3f} / {trend['home_advantage'].mean():.3f} / "
          f"{trend['home_advantage'].max():.3f}")
    for season in ALL_SEASONS:
        sub = winner_frame[winner_frame["season"] == season]
        if not sub.empty:
            print(f"    {season}: mean home_advantage {sub['home_advantage'].mean():.4f}, "
                  f"rho {sub['rho'].mean():.5f}")

    FIGURES_DIR.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(10, 4.5))
    ax.plot(trend["cutoff"], trend["home_advantage"], marker="o", ms=3, lw=1)
    ax.set_title(f"League One: fitted home advantage per weekly refit (xi={winner.xi:g})")
    ax.set_xlabel("cutoff (Monday)")
    ax.set_ylabel("home advantage (log scale)")
    ax.grid(alpha=0.3)
    fig.tight_layout()
    chart = FIGURES_DIR / "league_one_home_advantage_over_time.png"
    fig.savefig(chart, dpi=130)
    plt.close(fig)
    print(f"\nsaved chart -> {chart}")

    (FIGURES_DIR / "league_one_stage_a.csv").parent.mkdir(parents=True, exist_ok=True)
    stage_a.to_csv(FIGURES_DIR / "league_one_stage_a.csv", index=False)
    stage_b.to_csv(FIGURES_DIR / "league_one_stage_b.csv", index=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())