"""Walk-forward evaluation engine.

For a target season, refit on a weekly cadence and predict each week's matches
without ever seeing a match's own result or any later result.

Design
------
* **Cutoffs are Mondays.** For each Monday ``M`` the model is fitted on every
  match with ``date < M`` (strict, so the cutoff day itself is never in-sample)
  and then predicts matches in ``[M, M + 7 days)``.
* **Fits are cached** per ``(league, config_id, cutoff)`` so re-running a
  configuration is cheap.
* **Confirmation seasons are hard-refused** in both training and target data.
* **Predictions store lambda/mu/rho** so any market can be rebuilt later without
  refitting.

Goals model used for prediction:

    log E[home goals] = attack_home + defence_away + home_advantage
    log E[away goals] = attack_away + defence_home

(verified against the installed penaltyblog 1.12.2 by regression on its own
predictions; defence enters with a plus sign, so a LARGER defence coefficient
means a WORSE defence). Reproduces ``model.predict`` to within ~2e-4 in
probability — see ``tests/test_walkforward.py``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from core import splits
from penaltyblog.models import (
    DixonColesGoalModel,
    create_dixon_coles_grid,
    dixon_coles_weights,
)

CONFIRMATION_SEASONS = tuple(splits.split_seasons("confirmation"))
ALLOWED_SEASONS = tuple(splits.split_seasons("warmup")) + tuple(
    splits.split_seasons("discovery")
)

# penaltyblog's ``predict(..., max_goals=15)`` builds a 15x15 grid, i.e. goals
# 0..14. ``create_dixon_coles_grid`` interprets max_goals as the inclusive
# upper index, so pass 14 to match.
GRID_MAX_GOALS = 14

DATA_DIR = Path("data/historical")
CACHE_DIR = Path("data/cache/walkforward")
PRED_DIR = Path("data/predictions/league_one")

NEWCOMER_HORIZON_DAYS = 365
NEWCOMER_K = 10


@dataclass(frozen=True)
class Config:
    league: str = "league_one_t3"
    xi: float = 0.001
    drop_2020_21: bool = False
    newcomer: str = "exclude"  # exclude | league_avg | newcomer_prior
    grid_max_goals: int = GRID_MAX_GOALS

    @property
    def config_id(self) -> str:
        covid = "drop2021" if self.drop_2020_21 else "incl2021"
        return f"{self.league}__xi{self.xi:g}__{covid}__nw-{self.newcomer}"


# --------------------------------------------------------------------------- #
# guards
# --------------------------------------------------------------------------- #
def assert_no_confirmation(df: pd.DataFrame, what: str) -> None:
    bad = sorted(set(df["season"].unique()) & set(CONFIRMATION_SEASONS))
    if bad:
        raise RuntimeError(
            f"REFUSED: {what} contains confirmation season(s) {bad}. "
            "Confirmation data is locked."
        )


def assert_seasons_allowed(seasons) -> None:
    bad = sorted(set(seasons) & set(CONFIRMATION_SEASONS))
    if bad:
        raise RuntimeError(f"REFUSED: confirmation season(s) requested: {bad}")
    unknown = sorted(set(seasons) - set(ALLOWED_SEASONS))
    if unknown:
        raise RuntimeError(f"season(s) not in warmup+discovery: {unknown}")


# --------------------------------------------------------------------------- #
# data
# --------------------------------------------------------------------------- #
def load_pool(league: str) -> pd.DataFrame:
    warmup = splits.load_split("warmup", leagues=[league])
    discovery = splits.load_split("discovery", leagues=[league])
    df = pd.concat([warmup, discovery], ignore_index=True)
    df["date"] = pd.to_datetime(df["date"])
    assert_no_confirmation(df, f"{league} training pool")
    return df.sort_values("date").reset_index(drop=True)


def cutoff_mondays(df: pd.DataFrame) -> pd.DatetimeIndex:
    first = df["date"].min().normalize() - pd.Timedelta(days=int(df["date"].min().weekday()))
    last = df["date"].max().normalize() - pd.Timedelta(days=int(df["date"].max().weekday()))
    return pd.date_range(first, last, freq="7D")


# --------------------------------------------------------------------------- #
# fitting (cached)
# --------------------------------------------------------------------------- #
def _cache_path(config: Config, cutoff: pd.Timestamp) -> Path:
    """Fits depend on xi and the COVID switch only, not on the newcomer policy
    (which is applied at prediction time). Keying without ``newcomer`` lets all
    newcomer policies share one cached fit per cutoff."""
    covid = "drop2021" if config.drop_2020_21 else "incl2021"
    return CACHE_DIR / config.league / f"xi{config.xi:g}__{covid}" / f"{cutoff.date()}.json"


def fit_at(config: Config, train_df: pd.DataFrame, cutoff: pd.Timestamp) -> pd.Series:
    """Fit (or load a cached fit for) the model on ``train_df``."""
    cache = _cache_path(config, cutoff)
    if cache.exists():
        return pd.Series(json.loads(cache.read_text(encoding="utf-8")))

    weights = dixon_coles_weights(train_df["date"], xi=config.xi)
    model = DixonColesGoalModel(
        train_df["fthg"].to_numpy(),
        train_df["ftag"].to_numpy(),
        train_df["team_home"].to_numpy(),
        train_df["team_away"].to_numpy(),
        weights=weights,
    )
    model.fit()
    params = pd.Series({k: float(v) for k, v in model.get_params().items()})

    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(params.to_dict()), encoding="utf-8")
    return params


def training_frame_for(
    pool: pd.DataFrame, cutoff: pd.Timestamp, config: Config, min_rows: int = 100
) -> pd.DataFrame | None:
    """Training rows for a cutoff: strictly before it, never confirmation.

    ``date < cutoff`` is strict so a match on the cutoff day is never in-sample.
    """
    train = pool[pool["date"] < cutoff].copy()
    if config.drop_2020_21:
        train = train[train["season"] != "2020-2021"]
    assert_no_confirmation(train, f"training rows at cutoff {cutoff.date()}")
    if len(train) < min_rows:
        return None
    return train


def ratings_from(params: pd.Series) -> dict[str, tuple[float, float]]:
    teams = [k[len("attack_") :] for k in params.index if k.startswith("attack_")]
    return {t: (float(params[f"attack_{t}"]), float(params[f"defence_{t}"])) for t in teams}


# --------------------------------------------------------------------------- #
# newcomers
# --------------------------------------------------------------------------- #
def recent_matches(pool: pd.DataFrame, cutoff: pd.Timestamp, team: str) -> int:
    start = cutoff - timedelta(days=NEWCOMER_HORIZON_DAYS)
    window = pool[(pool["date"] >= start) & (pool["date"] < cutoff)]
    return int(((window["team_home"] == team) | (window["team_away"] == team)).sum())


def newcomer_type(pool: pd.DataFrame, cutoff: pd.Timestamp, team: str) -> str | None:
    """None if not a newcomer, else 'promoted_in' or 'relegated_in'.

    Proxy classification: a team with any League One history before the cutoff is
    treated as ``relegated_in`` (it is coming back down), otherwise
    ``promoted_in``.
    """
    if recent_matches(pool, cutoff, team) > 0:
        return None
    history = pool[(pool["date"] < cutoff)]
    seen = ((history["team_home"] == team) | (history["team_away"] == team)).any()
    return "relegated_in" if seen else "promoted_in"


def team_spell_starts(pool: pd.DataFrame, cutoff: pd.Timestamp, team: str) -> list[pd.Timestamp]:
    """Starts of a team's spells in this league before ``cutoff``.

    A new spell begins whenever more than ``NEWCOMER_HORIZON_DAYS`` passed since
    the team's previous match. ``spell_starts[0]`` is the team's debut in the
    data; later entries are genuine returns.
    """
    dates = (
        pool[(pool["date"] < cutoff) & ((pool["team_home"] == team) | (pool["team_away"] == team))][
            "date"
        ]
        .sort_values()
        .unique()
    )
    starts: list[pd.Timestamp] = []
    previous: pd.Timestamp | None = None
    for raw in dates:
        stamp = pd.Timestamp(raw)
        if previous is None or (stamp - previous).days > NEWCOMER_HORIZON_DAYS:
            starts.append(stamp)
        previous = stamp
    return starts


def newcomer_priors(
    pool: pd.DataFrame, params: pd.Series, cutoff: pd.Timestamp
) -> dict[str, tuple[float, float]]:
    """Mean fitted ratings of earlier newcomers of each type, as of ``cutoff``.

    Only uses the fit at ``cutoff`` (trained strictly before it) and genuine
    arrivals, so there is no leakage. Teams present from the very start of the
    data are not newcomers and are excluded, otherwise they would drag the prior
    onto the league average.

    Type is decided by *which spell* the arrival starts: the team's debut in the
    data is ``promoted_in``; a later return after a gap longer than a year is
    ``relegated_in`` (it has come back down). Teams whose debut falls before our
    data begins are invisible, so early seasons have few or no earlier newcomers.
    """
    ratings = ratings_from(params)
    league_attack = float(np.mean([a for a, _ in ratings.values()]))
    league_defence = float(np.mean([d for _, d in ratings.values()]))

    pool_start = pool["date"].min()

    buckets: dict[str, list[tuple[float, float]]] = {"promoted_in": [], "relegated_in": []}
    for team, (attack, defence) in ratings.items():
        starts = team_spell_starts(pool, cutoff, team)
        if not starts:
            continue
        for index, start in enumerate(starts):
            if (start - pool_start).days < NEWCOMER_HORIZON_DAYS:
                continue  # present before our data starts: not a visible arrival
            if (cutoff - start).days <= NEWCOMER_HORIZON_DAYS:
                continue  # still in their first year: not an *earlier* newcomer
            kind = "promoted_in" if index == 0 else "relegated_in"
            buckets[kind].append((attack, defence))

    priors = {}
    for kind, values in buckets.items():
        priors[kind] = (
            (float(np.mean([v[0] for v in values])), float(np.mean([v[1] for v in values])))
            if values
            else (league_attack, league_defence)
        )
    priors["league_avg"] = (league_attack, league_defence)
    priors["n_promoted_in"] = len(buckets["promoted_in"])
    priors["n_relegated_in"] = len(buckets["relegated_in"])
    return priors


def blended_rating(
    team: str,
    fitted: dict[str, tuple[float, float]],
    priors: dict[str, tuple[float, float]],
    prior_key: str,
    n_recent: int,
) -> tuple[float, float]:
    """Prior -> fitted blend with weight ``min(n / k, 1)``.

    A team with no fitted rating (a genuine newcomer) gets the prior outright.
    """
    prior = priors.get(prior_key, priors["league_avg"])
    if team not in fitted:
        return prior
    weight = min(n_recent / NEWCOMER_K, 1.0)
    attack = weight * fitted[team][0] + (1.0 - weight) * prior[0]
    defence = weight * fitted[team][1] + (1.0 - weight) * prior[1]
    return attack, defence


# --------------------------------------------------------------------------- #
# prediction
# --------------------------------------------------------------------------- #
def grid_probs(attack_h, defence_h, attack_a, defence_a, home_advantage, rho, max_goals):
    lam_h = float(np.exp(attack_h + defence_a + home_advantage))
    lam_a = float(np.exp(attack_a + defence_h))

    # create_dixon_coles_grid enforces strict rho bounds for the given lambdas;
    # clip defensively so an extreme fit can never crash a walk-forward run.
    rho_min = max(-1.0 / lam_h, -1.0 / lam_a)
    rho_max = min(1.0, 1.0 / (lam_h * lam_a))
    rho_used = float(min(max(rho, rho_min), rho_max))

    grid = create_dixon_coles_grid(lam_h, lam_a, rho_used, int(max_goals))
    expected_h = float((grid.home_goal_distribution() * np.arange(grid.grid.shape[0])).sum())
    expected_a = float((grid.away_goal_distribution() * np.arange(grid.grid.shape[1])).sum())
    return {
        "expected_home_goals": lam_h,
        "expected_away_goals": lam_a,
        "grid_expected_home_goals": expected_h,
        "grid_expected_away_goals": expected_a,
        "rho": rho_used,
        "p_home": float(grid.home_win),
        "p_draw": float(grid.draw),
        "p_away": float(grid.away_win),
        "p_over25": float(grid.total_goals("over", 2.5)),
        "p_btts": float(grid.btts_yes),
    }


def run(
    config: Config,
    target_seasons: list[str],
    pool: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Walk-forward predictions for ``target_seasons`` under ``config``."""
    assert_seasons_allowed(target_seasons)
    pool = load_pool(config.league) if pool is None else pool

    targets = pool[pool["season"].isin(target_seasons)].copy()
    assert_no_confirmation(targets, "target data")
    targets = targets.sort_values("date").reset_index(drop=True)

    records: list[dict] = []
    skipped_newcomer = 0

    for cutoff in cutoff_mondays(targets):
        week = targets[(targets["date"] >= cutoff) & (targets["date"] < cutoff + pd.Timedelta(days=7))]
        if week.empty:
            continue

        train = training_frame_for(pool, cutoff, config)
        if train is None:
            continue  # not enough history for a stable fit

        params = fit_at(config, train, cutoff)
        fitted = ratings_from(params)
        if config.newcomer == "newcomer_prior":
            priors = newcomer_priors(pool, params, cutoff)
        else:
            # league_avg only needs the fitted means; skip the (slower) scan
            # for earlier newcomers.
            ratings = fitted
            priors = {
                "league_avg": (
                    float(np.mean([a for a, _ in ratings.values()])),
                    float(np.mean([d for _, d in ratings.values()])),
                )
            }
        home_advantage, rho = float(params["home_advantage"]), float(params["rho"])

        for match in week.itertuples(index=False):
            home, away = match.team_home, match.team_away
            kind_h = newcomer_type(pool, cutoff, home)
            kind_a = newcomer_type(pool, cutoff, away)

            if config.newcomer == "exclude" and (
                home not in fitted or away not in fitted
            ):
                skipped_newcomer += 1
                continue

            # The prior used depends on the policy; the newcomer FLAGS always
            # reflect the true status so they mean the same thing across policies.
            key_h = (
                "league_avg" if config.newcomer == "league_avg" else (kind_h or "league_avg")
            )
            key_a = (
                "league_avg" if config.newcomer == "league_avg" else (kind_a or "league_avg")
            )

            n_h = recent_matches(pool, cutoff, home)
            n_a = recent_matches(pool, cutoff, away)
            attack_h, defence_h = blended_rating(home, fitted, priors, key_h, n_h)
            attack_a, defence_a = blended_rating(away, fitted, priors, key_a, n_a)

            probs = grid_probs(
                attack_h, defence_h, attack_a, defence_a,
                home_advantage, rho, config.grid_max_goals,
            )
            records.append(
                {
                    "match_key": match.id if hasattr(match, "id") else match.Index,
                    "cutoff": cutoff,
                    "season": match.season,
                    "date": match.date,
                    "team_home": home,
                    "team_away": away,
                    "fthg": int(match.fthg),
                    "ftag": int(match.ftag),
                    "home_advantage": home_advantage,
                    "home_newcomer": kind_h is not None,
                    "away_newcomer": kind_a is not None,
                    "home_newcomer_type": kind_h,
                    "away_newcomer_type": kind_a,
                    "home_recent_matches": n_h,
                    "away_recent_matches": n_a,
                    **probs,
                }
            )

    frame = pd.DataFrame.from_records(records)
    frame.attrs["config_id"] = config.config_id
    frame.attrs["skipped_newcomer"] = skipped_newcomer
    return frame


def save_predictions(frame: pd.DataFrame, config: Config) -> Path:
    PRED_DIR.mkdir(parents=True, exist_ok=True)
    path = PRED_DIR / f"{config.config_id}.parquet"
    frame.to_parquet(path)
    return path