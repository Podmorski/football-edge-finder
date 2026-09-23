"""Step 4 — COVID redesign.

``xi`` is fixed at 0.002 (the Stage A landscape was flat). The COVID option is
rebuilt so it can actually affect the seasons it is meant to affect:

* ``include``        — all training data used.
* ``exclude_after``  — 2020-21 removed from training for targets after that
                       season, but KEPT when the target is 2020-21 itself.
* ``downweight_0.5`` — 2020-21 decay weights halved for later targets.

By construction these can only change 2021-22 and 2022-23 predictions, and a
check below asserts that the earlier seasons are bit-identical across modes.

Pre-registered selection rule (see the ledger note written before this ran):
**lowest mean 1X2 log loss on 2021-22 and 2022-23** — post-hoc, discovery-only,
theory-driven, to be verified on confirmation.
"""

from __future__ import annotations

import sys
import time

import numpy as np
import pandas as pd

from core import ledger, walkforward as wf
from models import league_one_dixon_coles as m

SEASONS = ["2017-2018", "2018-2019", "2019-2020", "2020-2021", "2021-2022", "2022-2023"]
EARLIER = ["2017-2018", "2018-2019", "2019-2020", "2020-2021"]
SELECTION = ["2021-2022", "2022-2023"]
MODES = ["include", "exclude_after", "downweight_0.5"]


def outcome(frame: pd.DataFrame) -> np.ndarray:
    fthg, ftag = frame["fthg"].to_numpy(), frame["ftag"].to_numpy()
    out = np.full(len(frame), 1, dtype=int)
    out[fthg > ftag] = 0
    out[fthg < ftag] = 2
    return out


def log_loss(frame: pd.DataFrame) -> float:
    return m.log_loss(frame[["p_home", "p_draw", "p_away"]].to_numpy(), outcome(frame))


def ou_log_loss(frame: pd.DataFrame) -> float:
    over = (frame["fthg"] + frame["ftag"] > 2.5).to_numpy().astype(int)
    p = frame["p_over25"].to_numpy()
    return m.log_loss(np.column_stack([1 - p, p]), over)


def main() -> int:
    pool = wf.load_pool("league_one_t3")
    print("=" * 84)
    print("Step 4 — covid_mode selection (xi = 0.002 fixed)")
    print("=" * 84)

    frames = {}
    for mode in MODES:
        started = time.perf_counter()
        config = wf.Config(xi=0.002, covid_mode=mode, newcomer="newcomer_prior")
        frames[mode] = wf.run(config, SEASONS, pool=pool)
        print(f"  {mode:<15} {len(frames[mode])} predictions ({time.perf_counter()-started:.1f}s)")

    # sanity: modes must NOT change the earlier seasons
    print("\n--- sanity: earlier seasons identical across modes? ---")
    base = frames["include"]
    for mode in MODES[1:]:
        same = True
        for season in EARLIER:
            a = base[base["season"] == season][["p_home", "p_draw", "p_away"]].to_numpy()
            b = frames[mode][frames[mode]["season"] == season][["p_home", "p_draw", "p_away"]].to_numpy()
            if not np.allclose(a, b, atol=0):
                same = False
        print(f"  {mode:<15} earlier seasons unchanged: {same}")

    print("\n--- selection seasons ---")
    print(f"  {'mode':<15}{'2021-22 1X2':>14}{'2022-23 1X2':>14}{'mean 1X2':>12}"
          f"{'mean O/U':>12}")
    rows = []
    for mode in MODES:
        frame = frames[mode]
        per = {s: log_loss(frame[frame["season"] == s]) for s in SELECTION}
        per_ou = {s: ou_log_loss(frame[frame["season"] == s]) for s in SELECTION}
        rows.append(
            {
                "mode": mode,
                "2021-22": per["2021-2022"],
                "2022-23": per["2022-2023"],
                "mean_1x2": float(np.mean(list(per.values()))),
                "mean_ou": float(np.mean(list(per_ou.values()))),
            }
        )
        print(f"  {mode:<15}{per['2021-2022']:>14.4f}{per['2022-2023']:>14.4f}"
              f"{rows[-1]['mean_1x2']:>12.4f}{rows[-1]['mean_ou']:>12.4f}")

    table = pd.DataFrame(rows).sort_values("mean_1x2").reset_index(drop=True)
    winner = table.iloc[0]
    print(f"\nWinner by the pre-registered rule: covid_mode = {winner['mode']} "
          f"(mean 1X2 {winner['mean_1x2']:.4f})")

    for mode in MODES:
        for season in SEASONS:
            frame = frames[mode]
            sub = frame[frame["season"] == season]
            split = (
                "discovery:selection" if season in SELECTION else "discovery:earlier"
            )
            ledger.log_evaluation(
                league="league_one_t3",
                market="1X2",
                selection="home/draw/away",
                rule_config=f"step4 covid_mode={mode} xi=0.002 nw=newcomer_prior",
                split=f"{split}:{season}",
                n_predictions=len(sub),
                log_loss=round(log_loss(sub), 6),
                brier="",
                benchmark_name="",
                benchmark_log_loss="",
                n_bets="",
                roi="",
                mean_clv="",
                notes=f"covid redesign; OU2.5 log loss={ou_log_loss(sub):.6f}",
            )

    table.to_csv("reports/figures/league_one_covid_mode.csv", index=False)
    print(f"\nwrote reports/figures/league_one_covid_mode.csv")
    return 0


if __name__ == "__main__":
    sys.exit(main())