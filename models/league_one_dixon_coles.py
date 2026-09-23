"""League One Dixon-Coles — first model, a CORRECTNESS CHECK ONLY.

This is deliberately not tuned and not an edge hunt. Nothing here optimises
``xi``, and no ROI or edge is computed.

* ``xi = 0.001`` per day — **UNTUNED**, fixed by hand.
* Train: 2015-16 .. 2020-21. Holdout: 2021-22 (a *discovery* season).
* Fitted once; never refit on the holdout. Confirmation seasons are never loaded.

penaltyblog API used (verified against the installed 1.12.2, not from memory):

* ``penaltyblog.models.DixonColesGoalModel(goals_home, goals_away, teams_home,
  teams_away, weights=None, neutral_venue=None)``
* ``.fit(minimizer_options=None, use_gradient=True)``
* ``.predict(home_team, away_team, max_goals=15, normalize=True,
  neutral_venue=False) -> FootballProbabilityGrid``
* ``.predict_many(home_teams, away_teams, max_goals=15, normalize=True,
  neutral_venue=None) -> list[FootballProbabilityGrid]``
* ``.get_params() -> {"attack_<team>", "defence_<team>", "home_advantage", "rho"}``
* ``penaltyblog.models.dixon_coles_weights(dates, xi=0.0018, base_date=None)``
* ``penaltyblog.models.FootballProbabilityGrid`` with ``.grid`` (2-D ndarray),
  properties ``home_win`` / ``draw`` / ``away_win`` / ``btts_yes`` / ``btts_no``,
  and methods ``total_goals(over_under, strike)`` / ``totals(line)`` /
  ``exact_score(h, a)``.
"""

from __future__ import annotations

import time

import numpy as np
import pandas as pd

from core import ledger, splits
from penaltyblog.models import DixonColesGoalModel, dixon_coles_weights

LEAGUE_SLUG = "league_one_t3"
LEAGUE_LABEL = "League One (tier 3, target)"

# UNTUNED: fixed by hand, not optimised. Do not tune against the holdout.
XI_PER_DAY = 0.001
XI_LABEL = "UNTUNED"

TRAIN_SEASONS = [
    "2015-2016",
    "2016-2017",
    "2017-2018",
    "2018-2019",
    "2019-2020",
    "2020-2021",
]
HOLDOUT_SEASON = "2021-2022"

# The two training seasons immediately before the holdout, used for the
# "no history" exclusion rule.
RECENT_TRAIN_SEASONS = ["2019-2020", "2020-2021"]

MARKET_COLUMNS = {
    "AvgC": ("avg_ch", "avg_cd", "avg_ca"),
    "B365C": ("b365_ch", "b365_cd", "b365_ca"),
    "Avg": ("avg_h", "avg_d", "avg_a"),
}


# --------------------------------------------------------------------------- #
# data
# --------------------------------------------------------------------------- #
def load_matches() -> pd.DataFrame:
    """Load warmup + discovery for League One and sort by date.

    Never touches the confirmation split.
    """
    warmup = splits.load_split("warmup", leagues=[LEAGUE_SLUG])
    discovery = splits.load_split("discovery", leagues=[LEAGUE_SLUG])
    df = pd.concat([warmup, discovery], ignore_index=True)
    df["date"] = pd.to_datetime(df["date"])
    return df.sort_values("date").reset_index(drop=True)


def training_frame(df: pd.DataFrame) -> pd.DataFrame:
    return df[df["season"].isin(TRAIN_SEASONS)].reset_index(drop=True).copy()


def holdout_frame(df: pd.DataFrame) -> pd.DataFrame:
    return df[df["season"] == HOLDOUT_SEASON].reset_index(drop=True).copy()


def eligible_teams(train: pd.DataFrame) -> set[str]:
    """Teams that played in the two training seasons before the holdout."""
    recent = train[train["season"].isin(RECENT_TRAIN_SEASONS)]
    return set(recent["team_home"]) | set(recent["team_away"])


# --------------------------------------------------------------------------- #
# fitting / prediction
# --------------------------------------------------------------------------- #
def fit(train: pd.DataFrame) -> tuple[DixonColesGoalModel, float]:
    weights = dixon_coles_weights(train["date"], xi=XI_PER_DAY)
    model = DixonColesGoalModel(
        train["fthg"].to_numpy(),
        train["ftag"].to_numpy(),
        train["team_home"].to_numpy(),
        train["team_away"].to_numpy(),
        weights=weights,
    )
    started = time.perf_counter()
    model.fit()
    elapsed = time.perf_counter() - started
    return model, elapsed


def grids_for(model: DixonColesGoalModel, frame: pd.DataFrame):
    return model.predict_many(
        frame["team_home"].to_numpy(), frame["team_away"].to_numpy()
    )


def outcome_probs(model: DixonColesGoalModel, frame: pd.DataFrame) -> np.ndarray:
    """1X2 probabilities (home, draw, away) for every match in ``frame``."""
    grids = grids_for(model, frame)
    return np.array([[g.home_win, g.draw, g.away_win] for g in grids], dtype=float)


# --------------------------------------------------------------------------- #
# metrics
# --------------------------------------------------------------------------- #
def actual_outcome(frame: pd.DataFrame) -> np.ndarray:
    """0 = home win, 1 = draw, 2 = away win."""
    fthg = frame["fthg"].to_numpy()
    ftag = frame["ftag"].to_numpy()
    out = np.full(len(frame), 1, dtype=int)
    out[fthg > ftag] = 0
    out[fthg < ftag] = 2
    return out


def log_loss(probs: np.ndarray, actual: np.ndarray) -> float:
    p = np.clip(probs[np.arange(len(actual)), actual], 1e-15, 1.0)
    return float(-np.mean(np.log(p)))


def brier(probs: np.ndarray, actual: np.ndarray) -> float:
    onehot = np.zeros_like(probs)
    onehot[np.arange(len(actual)), actual] = 1.0
    return float(np.mean(np.sum((probs - onehot) ** 2, axis=1)))


def base_rates(train: pd.DataFrame) -> np.ndarray:
    actual = actual_outcome(train)
    return np.array([np.mean(actual == k) for k in (0, 1, 2)])


def market_probs(frame: pd.DataFrame) -> tuple[np.ndarray, str, np.ndarray, float]:
    """De-margined closing 1X2 probabilities.

    Preference: AvgC -> B365C -> pre-match Avg. Returns
    (probs, source_name, kept_mask, mean_margin_removed). ``probs`` and the
    margin are restricted to rows in ``kept_mask``.
    """
    n = len(frame)
    probs = np.full((n, 3), np.nan)
    sources_used: list[str] = []
    remaining = np.ones(n, dtype=bool)

    for name, cols in MARKET_COLUMNS.items():
        if not all(c in frame.columns for c in cols):
            continue
        odds = frame.loc[:, list(cols)].astype(float).to_numpy()
        valid = remaining & np.all(np.isfinite(odds) & (odds > 1.0), axis=1)
        if valid.any():
            raw = 1.0 / odds[valid]
            probs[valid] = raw / raw.sum(axis=1, keepdims=True)
            remaining &= ~valid
            sources_used.append(name)
        if not remaining.any():
            break

    kept = np.all(np.isfinite(probs), axis=1)

    booksum = np.full(n, np.nan)
    for name, cols in MARKET_COLUMNS.items():
        if not all(c in frame.columns for c in cols):
            continue
        o = frame.loc[:, list(cols)].astype(float).to_numpy()
        valid = np.all(np.isfinite(o) & (o > 1.0), axis=1) & np.isnan(booksum)
        booksum[valid] = (1.0 / o[valid]).sum(axis=1)

    margins = booksum[kept] - 1.0
    source = "+".join(sources_used) if sources_used else "none"
    return probs[kept], source, kept, float(np.mean(margins))


def reliability_table(prob_home: np.ndarray, actual: np.ndarray, bins: int = 5):
    """5-bin reliability for P(home): mean predicted vs observed home-win rate."""
    edges = np.linspace(0.0, 1.0, bins + 1)
    is_home = (actual == 0).astype(float)
    idx = np.clip(np.digitize(prob_home, edges[1:-1]), 0, bins - 1)
    rows = []
    for b in range(bins):
        mask = idx == b
        if mask.sum() == 0:
            rows.append((f"{edges[b]:.1f}-{edges[b+1]:.1f}", 0, None, None))
            continue
        rows.append(
            (
                f"{edges[b]:.1f}-{edges[b+1]:.1f}",
                int(mask.sum()),
                float(prob_home[mask].mean()),
                float(is_home[mask].mean()),
            )
        )
    return rows


def spearman(a: pd.Series, b: pd.Series) -> float:
    return float(a.rank().corr(b.rank()))


def final_table_points(train: pd.DataFrame, season: str) -> pd.Series:
    """Points per team for a season, computed from results."""
    sub = train[train["season"] == season]
    points: dict[str, int] = {}
    for row in sub.itertuples(index=False):
        home, away = row.team_home, row.team_away
        hg, ag = int(row.fthg), int(row.ftag)
        points.setdefault(home, 0)
        points.setdefault(away, 0)
        if hg > ag:
            points[home] += 3
        elif hg < ag:
            points[away] += 3
        else:
            points[home] += 1
            points[away] += 1
    return pd.Series(points, dtype=float)


# --------------------------------------------------------------------------- #
# correctness-check runner
# --------------------------------------------------------------------------- #
def expected_goals(grid) -> tuple[float, float]:
    h = float((grid.home_goal_distribution() * np.arange(grid.grid.shape[0])).sum())
    a = float((grid.away_goal_distribution() * np.arange(grid.grid.shape[1])).sum())
    return h, a


def sanity_checks(model, train, remaining, train_grids, holdout_grids):
    """Return a list of (name, passed, detail) sanity checks."""
    checks = []

    masses = np.array([g.grid.sum() for g in holdout_grids])
    trunc = float(1.0 - masses.mean())
    checks.append(("grid mass within 0.01 of 1", abs(trunc) <= 0.01,
                   f"mean mass={masses.mean():.6f}, truncation loss={trunc:.6f}"))

    trio = np.array([[g.home_win, g.draw, g.away_win] for g in holdout_grids])
    dev = float(np.max(np.abs(trio.sum(axis=1) - 1.0)))
    checks.append(("P(H)+P(D)+P(A)=1 (1e-6)", dev <= 1e-6, f"max deviation={dev:.2e}"))

    ou = np.array([[g.total_goals("over", 2.5), g.total_goals("under", 2.5)] for g in holdout_grids])
    ouv = float(np.max(np.abs(ou.sum(axis=1) - 1.0)))
    checks.append(("O/U 2.5 sums to 1", ouv <= 1e-9, f"max deviation={ouv:.2e}"))

    btts = np.array([[g.btts_yes, g.btts_no] for g in holdout_grids])
    bv = float(np.max(np.abs(btts.sum(axis=1) - 1.0)))
    checks.append(("BTTS sums to 1", bv <= 1e-9, f"max deviation={bv:.2e}"))

    pairs = np.array([expected_goals(g) for g in train_grids])
    pred_h, pred_a = float(pairs[:, 0].mean()), float(pairs[:, 1].mean())
    act_h, act_a = float(train["fthg"].mean()), float(train["ftag"].mean())
    gap_h, gap_a = abs(pred_h - act_h), abs(pred_a - act_a)
    checks.append(("training mean goals match (gap<=0.15)", max(gap_h, gap_a) <= 0.15,
                   f"home {pred_h:.3f} vs {act_h:.3f} (gap {gap_h:.3f}); "
                   f"away {pred_a:.3f} vs {act_a:.3f} (gap {gap_a:.3f})"))

    params = model.get_params()
    ha, rho = params["home_advantage"], params["rho"]
    checks.append(("home advantage > 0", ha > 0, f"home_advantage={ha:.4f}"))
    checks.append(("rho in [-0.3, 0.1]", -0.3 <= rho <= 0.1, f"rho={rho:.4f}"))

    attack = pd.Series({t: params[f"attack_{t}"] for t in model.teams})
    defence = pd.Series({t: params[f"defence_{t}"] for t in model.teams})
    table = final_table_points(train, RECENT_TRAIN_SEASONS[-1])
    strength = (attack - defence).reindex(table.index)
    rho_s = spearman(strength, table)
    checks.append(("Spearman(attack-defence, final table)", rho_s > 0.5,
                   f"rho={rho_s:.3f} on {RECENT_TRAIN_SEASONS[-1]}"))
    return checks, attack, defence


def main() -> int:
    print("=" * 74)
    print("League One Dixon-Coles — CORRECTNESS CHECK ONLY")
    print(f"xi = {XI_PER_DAY} per day ({XI_LABEL}) — no tuning performed")
    print("=" * 74)

    matches = load_matches()
    train = training_frame(matches)
    holdout = holdout_frame(matches)
    print(f"loaded League One matches : {len(matches)}")
    print(f"training matches          : {len(train)} ({TRAIN_SEASONS[0]} .. {TRAIN_SEASONS[-1]})")
    print(f"holdout matches           : {len(holdout)} ({HOLDOUT_SEASON}, discovery season)")

    eligible = eligible_teams(train)
    ok = holdout["team_home"].isin(eligible) & holdout["team_away"].isin(eligible)
    excluded = holdout[~ok]
    remaining = holdout[ok].reset_index(drop=True)
    holdout_teams = set(holdout["team_home"]) | set(holdout["team_away"])
    ineligible = sorted(holdout_teams - eligible)
    print(f"eligible teams            : {len(eligible)}")
    print(f"holdout excluded (no history in {RECENT_TRAIN_SEASONS}): {len(excluded)}")
    print(f"  ineligible teams        : {ineligible}")

    model, fit_seconds = fit(train)
    params = model.get_params()
    weights = dixon_coles_weights(train["date"], xi=XI_PER_DAY)
    print()
    print("--- fit diagnostics ---")
    print(f"convergence success : {model._res.success}")
    print(f"message             : {model._res.message}")
    print(f"log-likelihood      : {model.loglikelihood:.2f}")
    print(f"AIC                 : {model.aic:.2f}")
    print(f"home advantage      : {params['home_advantage']:.4f}")
    print(f"rho                 : {params['rho']:.4f}")
    print(f"n teams             : {model.n_teams}")
    print(f"fit time            : {fit_seconds:.2f}s")
    print(f"decay weights       : min={weights.min():.4f} max={weights.max():.4f} "
          f"mean={weights.mean():.4f} (xi={XI_PER_DAY}/day, base=latest training match)")

    attack = pd.Series({t: params[f"attack_{t}"] for t in model.teams})
    defence = pd.Series({t: params[f"defence_{t}"] for t in model.teams})
    # Sign convention (verified empirically on 2020-21: corr with goals scored
    # +0.92 for attack, corr with goals conceded +0.93 for defence): a LARGER
    # defence coefficient means a WORSE defence.
    def show(tag: str, series: pd.Series, largest: bool) -> None:
        picked = series.nlargest(5) if largest else series.nsmallest(5)
        print(f"{tag:<34}: " + ", ".join(f"{t}={v:.3f}" for t, v in picked.items()))

    show("attack  best 5 (highest coeff)", attack, True)
    show("attack  worst 5 (lowest coeff)", attack, False)
    show("defence best 5 (lowest coeff)", defence, False)
    show("defence worst 5 (highest coeff)", defence, True)

    holdout_grids = grids_for(model, remaining)
    train_grids = grids_for(model, train)
    checks, attack, defence = sanity_checks(model, train, remaining, train_grids, holdout_grids)

    print()
    print("--- sanity checks ---")
    for name, passed, detail in checks:
        print(f"[{'PASS' if passed else 'FAIL'}] {name}: {detail}")

    # ---------- holdout comparison (same subset for all three) ---------- #
    probs_market, source, keep_mask, mean_margin = market_probs(remaining)

    eval_df = remaining[keep_mask].reset_index(drop=True)
    probs_model = outcome_probs(model, eval_df)
    naive = base_rates(train)
    probs_naive = np.tile(naive, (len(eval_df), 1))
    probs_mkt, source, _, mean_margin = market_probs(eval_df)
    actual = actual_outcome(eval_df)

    print()
    print(f"--- holdout comparison ({HOLDOUT_SEASON}) ---")
    print(f"matches evaluated     : {len(eval_df)} (same subset for all three)")
    print(f"market odds source    : {source}")
    print(f"mean margin removed   : {mean_margin:.4f}")
    print()
    print(f"{'approach':<10} {'log loss':>10} {'brier':>10}")
    rows = {
        "model": (log_loss(probs_model, actual), brier(probs_model, actual)),
        "naive": (log_loss(probs_naive, actual), brier(probs_naive, actual)),
        "market": (log_loss(probs_mkt, actual), brier(probs_mkt, actual)),
    }
    for name in ("model", "naive", "market"):
        ll, br = rows[name]
        print(f"{name:<10} {ll:>10.4f} {br:>10.4f}")

    print()
    print("reliability for P(home) (5 bins): predicted | observed")
    for approach, prob in (("model", probs_model[:, 0]), ("market", probs_mkt[:, 0])):
        print(f"  {approach}:")
        for bucket, n, pred, obs in reliability_table(prob, actual):
            if n == 0:
                print(f"    {bucket}: (empty)")
            else:
                print(f"    {bucket}: n={n:<4} predicted={pred:.3f} observed={obs:.3f}")

    # ---------- ledger ---------- #
    rule = f"dixon_coles xi={XI_PER_DAY} ({XI_LABEL})"
    for name, prob in (("model", probs_model), ("naive_base_rates", probs_naive)):
        ledger.log_evaluation(
            league=LEAGUE_SLUG,
            market="1X2",
            selection="home/draw/away",
            rule_config=rule if name == "model" else "training base rates",
            split=f"discovery:{HOLDOUT_SEASON}",
            n_predictions=len(eval_df),
            log_loss=round(log_loss(prob, actual), 6),
            brier=round(brier(prob, actual), 6),
            benchmark_name=f"market_{source}",
            benchmark_log_loss=round(rows["market"][0], 6),
            n_bets="",
            roi="",
            mean_clv="",
            notes=f"correctness check only; excluded={len(excluded)}; {name}",
        )
    ledger.log_evaluation(
        league=LEAGUE_SLUG, market="1X2", selection="home/draw/away",
        rule_config=f"de-margined closing odds ({source})",
        split=f"discovery:{HOLDOUT_SEASON}", n_predictions=len(eval_df),
        log_loss=round(rows["market"][0], 6), brier=round(rows["market"][1], 6),
        benchmark_name=f"market_{source}", benchmark_log_loss=round(rows["market"][0], 6),
        n_bets="", roi="", mean_clv="",
        notes=f"benchmark; mean margin removed={mean_margin:.4f}",
    )
    print(f"\nappended 3 rows to research/ledger.csv")

    verdict = ""
    if rows["model"][0] < rows["naive"][0] and rows["model"][0] > rows["market"][0]:
        verdict = "beats naive, loses to market (expected for an untuned model)"
    else:
        verdict = "does NOT match the expected 'beats naive, loses to market' pattern"
    print(f"interpretation: {verdict}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())