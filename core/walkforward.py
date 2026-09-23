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
from penaltyblog.models import DixonColesGoalModel, dixon_coles_weights

CONFIRMATION_SEASONS = tuple(splits.split_seasons("confirmation"))
ALLOWED_SEASONS = tuple(splits.split_seasons("warmup")) + tuple(
    splits.split_seasons("discovery")
)

# penaltyblog's ``predict(..., max_goals=15)`` builds a 15x15 grid (goals 0..14).
# We now go through penaltyblog's own compiled path, so use its default.
GRID_MAX_GOALS = 15

DATA_DIR = Path("data/historical")
CACHE_DIR = Path("data/cache/walkforward")
PRED_DIR = Path("data/predictions/league_one")
LABELS_PATH = Path("data/auxiliary/newcomer_labels.parquet")

NEWCOMER_HORIZON_DAYS = 365
NEWCOMER_K = 10


@dataclass(frozen=True)
class Config:
    league: str = "league_one_t3"
    xi: float = 0.002
    # include | exclude_after | downweight_0.5
    #   exclude_after : 2020-21 is in training only when the target IS 2020-21
    #   downweight_0.5: 2020-21 weights are halved for later targets
    covid_mode: str = "include"
    newcomer: str = "newcomer_prior"  # exclude | league_avg | newcomer_prior
    grid_max_goals: int = GRID_MAX_GOALS

    @property
    def config_id(self) -> str:
        return f"{self.league}__xi{self.xi:g}__{self.covid_mode}__nw-{self.newcomer}"


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
    """Fits depend on xi and covid_mode only, not on the newcomer policy (which
    is applied at prediction time). Keying without ``newcomer`` lets all newcomer
    policies share one cached fit per cutoff."""
    return (
        CACHE_DIR
        / config.league
        / f"xi{config.xi:g}__{config.covid_mode}"
        / f"{cutoff.date()}.json"
    )


def _decay_weights(
    train: pd.DataFrame, config: Config, target_season: str | None
) -> np.ndarray:
    """Time-decay weights, with the COVID downweight applied when configured."""
    weights = np.asarray(dixon_coles_weights(train["date"], xi=config.xi), dtype=float)
    if (
        config.covid_mode == "downweight_0.5"
        and target_season is not None
        and target_season > "2020-2021"
    ):
        mask = (train["season"] == "2020-2021").to_numpy()
        weights = weights.copy()
        weights[mask] *= 0.5
    return weights


def fit_at(
    config: Config, train_df: pd.DataFrame, cutoff: pd.Timestamp, target_season: str | None = None
) -> pd.Series:
    """Fit (or load a cached fit for) the model on ``train_df``."""
    cache = _cache_path(config, cutoff)
    if cache.exists():
        return pd.Series(json.loads(cache.read_text(encoding="utf-8")))

    weights = _decay_weights(train_df, config, target_season)
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
    pool: pd.DataFrame,
    cutoff: pd.Timestamp,
    config: Config,
    target_season: str | None = None,
    min_rows: int = 100,
) -> pd.DataFrame | None:
    """Training rows for a cutoff: strictly before it, never confirmation.

    ``date < cutoff`` is strict so a match on the cutoff day is never in-sample.
    ``covid_mode == 'exclude_after'`` removes 2020-21 from training for targets
    after that season, but keeps it when the target IS 2020-21 (so the option can
    actually affect the target it is meant to affect).
    """
    train = pool[pool["date"] < cutoff].copy()
    if (
        config.covid_mode == "exclude_after"
        and target_season is not None
        and target_season > "2020-2021"
    ):
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


def load_labels() -> dict[tuple[str, str], str]:
    """(season, team) -> 'relegated_in' | 'promoted_in' | 'other'.

    Derived from auxiliary E1/E3 by ``newcomer_labels.py``. Known before each
    season starts, so using them is not leakage.
    """
    if not LABELS_PATH.exists():
        return {}
    frame = pd.read_parquet(LABELS_PATH)
    return {(row.season, row.team): row.label for row in frame.itertuples(index=False)}


def season_start_dates(pool: pd.DataFrame) -> dict[str, pd.Timestamp]:
    return pool.groupby("season")["date"].min().to_dict()


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
    pool: pd.DataFrame,
    params: pd.Series,
    cutoff: pd.Timestamp,
    label_map: dict[tuple[str, str], str] | None = None,
    target_season: str | None = None,
) -> dict:
    """Mean fitted ratings of earlier newcomers of each type, as of ``cutoff``.

    Types come from the auxiliary E1/E3 labels (``newcomer_labels.py``), not from
    a League-One-only heuristic. Only newcomers from seasons **strictly before**
    the target season are used, and only once they are past their first year, so
    there is no leakage.
    """
    ratings = ratings_from(params)
    league_attack = float(np.mean([a for a, _ in ratings.values()]))
    league_defence = float(np.mean([d for _, d in ratings.values()]))

    labels = label_map if label_map is not None else load_labels()
    starts = season_start_dates(pool)

    buckets: dict[str, list[tuple[float, float]]] = {
        "promoted_in": [],
        "relegated_in": [],
        "other": [],
    }
    for (season, team), label in labels.items():
        if target_season is not None and season >= target_season:
            continue
        season_start = starts.get(season)
        if season_start is None:
            continue
        if (cutoff - season_start).days <= NEWCOMER_HORIZON_DAYS:
            continue  # not yet past their first year in the league
        if team not in ratings:
            continue
        buckets.setdefault(label, []).append(ratings[team])

    priors: dict = {}
    for kind, values in buckets.items():
        priors[kind] = (
            (float(np.mean([v[0] for v in values])), float(np.mean([v[1] for v in values])))
            if values
            else (league_attack, league_defence)
        )
    priors["league_avg"] = (league_attack, league_defence)
    priors["n_promoted_in"] = len(buckets["promoted_in"])
    priors["n_relegated_in"] = len(buckets["relegated_in"])
    priors["n_other"] = len(buckets["other"])
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
def model_from_ratings(
    ratings: dict[str, tuple[float, float]], home_advantage: float, rho: float
) -> DixonColesGoalModel:
    """Rebuild a predict-capable model from persisted ratings.

    All markets are then produced by penaltyblog's own compiled grid, so results
    are bit-identical to ``.predict()``. Ratings may include injected newcomer
    values; the attack-sum constraint only binds during fitting.
    """
    teams = sorted(ratings)
    model = DixonColesGoalModel(
        [0, 1], [0, 1], ["__placeholder_a", "__placeholder_b"], ["__placeholder_b", "__placeholder_a"]
    )
    model.teams = np.array(teams, dtype=object)
    model.n_teams = len(teams)
    model.team_to_idx = {team: i for i, team in enumerate(teams)}
    attack = np.array([ratings[t][0] for t in teams], dtype=np.float64)
    defence = np.array([ratings[t][1] for t in teams], dtype=np.float64)
    model._params = np.concatenate([attack, defence, [home_advantage, rho]])
    model.fitted = True
    return model


def markets_from_grid(grid) -> dict:
    """All markets for one fixture, straight from penaltyblog's grid."""
    return {
        "expected_home_goals": float(grid.home_goal_expectation),
        "expected_away_goals": float(grid.away_goal_expectation),
        "grid_expected_home_goals": float(
            (grid.home_goal_distribution() * np.arange(grid.grid.shape[0])).sum()
        ),
        "grid_expected_away_goals": float(
            (grid.away_goal_distribution() * np.arange(grid.grid.shape[1])).sum()
        ),
        "p_home": float(grid.home_win),
        "p_draw": float(grid.draw),
        "p_away": float(grid.away_win),
        "p_over25": float(grid.total_goals("over", 2.5)),
        "p_btts": float(grid.btts_yes),
        # Full total-goals pmf (index = total goals), for dispersion diagnostics.
        "total_goals_pmf": [float(v) for v in grid.total_goals_distribution()],
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
    label_map = load_labels()

    for cutoff in cutoff_mondays(targets):
        week = targets[(targets["date"] >= cutoff) & (targets["date"] < cutoff + pd.Timedelta(days=7))]
        if week.empty:
            continue

        week_season = week["season"].iloc[0]
        train = training_frame_for(pool, cutoff, config, week_season)
        if train is None:
            continue  # not enough history for a stable fit

        params = fit_at(config, train, cutoff, week_season)
        fitted = ratings_from(params)
        if config.newcomer == "newcomer_prior":
            priors = newcomer_priors(pool, params, cutoff, label_map, week_season)
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

        # Build one model per cutoff with the policy-adjusted ratings, then let
        # penaltyblog produce every market (exact parity with .predict()).
        ratings_map = dict(fitted)
        pending: list[dict] = []

        for match in week.itertuples(index=False):
            home, away = match.team_home, match.team_away
            # Detection stays the 365-day rule; the TYPE comes from E1/E3 labels.
            kind_h = (
                label_map.get((match.season, home))
                if recent_matches(pool, cutoff, home) == 0
                else None
            )
            kind_a = (
                label_map.get((match.season, away))
                if recent_matches(pool, cutoff, away) == 0
                else None
            )

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
            ratings_map[home] = blended_rating(home, fitted, priors, key_h, n_h)
            ratings_map[away] = blended_rating(away, fitted, priors, key_a, n_a)

            pending.append(
                {
                    "match_key": match.id,
                    "cutoff": cutoff,
                    "season": match.season,
                    "date": match.date,
                    "team_home": home,
                    "team_away": away,
                    "fthg": int(match.fthg),
                    "ftag": int(match.ftag),
                    "home_advantage": home_advantage,
                    "rho": rho,
                    "home_newcomer": kind_h is not None,
                    "away_newcomer": kind_a is not None,
                    "home_newcomer_type": kind_h,
                    "away_newcomer_type": kind_a,
                    "home_recent_matches": n_h,
                    "away_recent_matches": n_a,
                    "home_blend_weight": (
                        min(n_h / NEWCOMER_K, 1.0) if home in fitted else 0.0
                    ),
                    "away_blend_weight": (
                        min(n_a / NEWCOMER_K, 1.0) if away in fitted else 0.0
                    ),
                }
            )

        if not pending:
            continue

        model = model_from_ratings(ratings_map, home_advantage, rho)
        grids = model.predict_many(
            [row["team_home"] for row in pending],
            [row["team_away"] for row in pending],
            max_goals=config.grid_max_goals,
        )
        for meta, grid in zip(pending, grids):
            records.append({**meta, **markets_from_grid(grid)})

    frame = pd.DataFrame.from_records(records)
    frame.attrs["config_id"] = config.config_id
    frame.attrs["skipped_newcomer"] = skipped_newcomer
    return frame


def grid_parity(n: int = 500, seed: int = 0, xi: float = 0.002) -> dict:
    """Compare the rebuilt-model path against ``penaltyblog`` ``.predict()``.

    Both sides now run the same compiled grid with identical parameters, so the
    expected difference is exactly zero.
    """
    pool = load_pool("league_one_t3")
    train = pool[pool["date"] < pd.Timestamp("2022-07-01")]
    model = DixonColesGoalModel(
        train["fthg"].to_numpy(),
        train["ftag"].to_numpy(),
        train["team_home"].to_numpy(),
        train["team_away"].to_numpy(),
        weights=dixon_coles_weights(train["date"], xi=xi),
    )
    model.fit()
    params = model.get_params()
    ratings = {
        t: (float(params[f"attack_{t}"]), float(params[f"defence_{t}"]))
        for t in model.teams
    }
    rebuilt = model_from_ratings(
        ratings, float(params["home_advantage"]), float(params["rho"])
    )

    sample = train.sample(min(n, len(train)), random_state=seed)
    worst = 0.0
    for row in sample.itertuples(index=False):
        ref = model.predict(row.team_home, row.team_away)
        mine = rebuilt.predict(row.team_home, row.team_away)
        worst = max(
            worst,
            abs(ref.home_win - mine.home_win),
            abs(ref.draw - mine.draw),
            abs(ref.away_win - mine.away_win),
            abs(ref.total_goals("over", 2.5) - mine.total_goals("over", 2.5)),
            abs(ref.btts_yes - mine.btts_yes),
        )
    return {"n": len(sample), "max_abs_diff": worst}


def save_predictions(frame: pd.DataFrame, config: Config) -> Path:
    PRED_DIR.mkdir(parents=True, exist_ok=True)
    path = PRED_DIR / f"{config.config_id}.parquet"
    frame.to_parquet(path)
    return path