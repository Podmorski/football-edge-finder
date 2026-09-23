"""Walk-forward engine tests: leakage guard, confirmation refusal, and the
accuracy of the manual lambda path against ``model.predict``.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from core import walkforward as wf
from models import league_one_dixon_coles as m


@pytest.fixture(scope="module")
def pool():
    return wf.load_pool("league_one_t3")


def test_no_training_row_is_on_or_after_the_cutoff(pool):
    """Leakage guard: every training row must strictly precede the cutoff."""
    config = wf.Config()
    targets = pool[pool["season"].isin(["2021-2022"])]
    cutoffs = wf.cutoff_mondays(targets)

    checked = 0
    for cutoff in cutoffs:
        train = wf.training_frame_for(pool, cutoff, config)
        if train is None:
            continue
        assert len(train) > 0
        assert train["date"].max() < cutoff, f"leak at cutoff {cutoff}"
        assert not ((train["date"] >= cutoff).any())
        checked += 1
    assert checked > 30, f"only checked {checked} cutoffs"


def test_drop_2020_21_removes_that_season_from_training(pool):
    config = wf.Config(drop_2020_21=True)
    cutoff = pd.Timestamp("2022-01-03")
    train = wf.training_frame_for(pool, cutoff, config)
    assert "2020-2021" not in set(train["season"].unique())

    keep = wf.training_frame_for(pool, cutoff, wf.Config(drop_2020_21=False))
    assert "2020-2021" in set(keep["season"].unique())


def test_confirmation_seasons_are_hard_refused():
    with pytest.raises(RuntimeError, match="confirmation"):
        wf.assert_seasons_allowed(["2023-2024"])

    frame = pd.DataFrame({"season": ["2023-2024"], "date": [pd.Timestamp("2024-01-01")]})
    with pytest.raises(RuntimeError, match="confirmation"):
        wf.assert_no_confirmation(frame, "test data")


def test_manual_lambda_path_matches_penaltyblog_predict(pool):
    """Documents and bounds the known deviation.

    penaltyblog builds its fit-time grid in compiled code and its
    ``create_dixon_coles_grid`` helper in pure Python; the two apply the
    Dixon-Coles tau to the four low-score cells slightly differently, so the
    1X2 probabilities differ by up to ~1.1e-3 (measured). Everything else
    (lambdas, grid mass, Poisson body) agrees to ~1e-12. Log-loss impact is
    ~1e-5, far below the effects this project measures.
    """
    train = pool[pool["season"] != "2021-2022"]
    model, _ = m.fit(train)
    params = model.get_params()

    worst = 0.0
    for row in train.sample(120, random_state=3).itertuples(index=False):
        reference = model.predict(row.team_home, row.team_away)
        mine = wf.grid_probs(
            params[f"attack_{row.team_home}"],
            params[f"defence_{row.team_home}"],
            params[f"attack_{row.team_away}"],
            params[f"defence_{row.team_away}"],
            params["home_advantage"],
            params["rho"],
            wf.GRID_MAX_GOALS,
        )
        worst = max(
            worst,
            abs(reference.home_win - mine["p_home"]),
            abs(reference.draw - mine["p_draw"]),
            abs(reference.away_win - mine["p_away"]),
            abs(reference.total_goals("over", 2.5) - mine["p_over25"]),
            abs(reference.btts_yes - mine["p_btts"]),
        )
    assert worst < 2e-3, f"manual path deviates by {worst:.2e}"


def test_run_produces_one_row_per_predicted_match(pool):
    config = wf.Config()
    frame = wf.run(config, ["2021-2022"], pool=pool)
    assert not frame.empty
    assert frame["match_key"].is_unique
    assert set(frame["season"]) == {"2021-2022"}
    for column in (
        "expected_home_goals",
        "expected_away_goals",
        "rho",
        "p_home",
        "p_draw",
        "p_away",
        "p_over25",
        "p_btts",
        "home_newcomer",
        "away_newcomer",
    ):
        assert column in frame.columns, column
    assert np.allclose(frame[["p_home", "p_draw", "p_away"]].sum(axis=1), 1.0, atol=1e-9)
    # every prediction belongs to the week starting at its cutoff
    assert ((frame["date"] >= frame["cutoff"]).all())
    assert ((frame["date"] < frame["cutoff"] + pd.Timedelta(days=7)).all())