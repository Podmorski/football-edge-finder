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
        train = wf.training_frame_for(pool, cutoff, config, "2021-2022")
        if train is None:
            continue
        assert len(train) > 0
        assert train["date"].max() < cutoff, f"leak at cutoff {cutoff}"
        assert not ((train["date"] >= cutoff).any())
        checked += 1
    assert checked > 30, f"only checked {checked} cutoffs"


def test_exclude_after_keeps_2020_21_only_for_a_2020_21_target(pool):
    config = wf.Config(covid_mode="exclude_after")
    cutoff = pd.Timestamp("2022-01-03")

    later = wf.training_frame_for(pool, cutoff, config, target_season="2021-2022")
    assert "2020-2021" not in set(later["season"].unique())

    # When the target IS 2020-21 the season is kept, so the option can affect it.
    during = wf.training_frame_for(pool, pd.Timestamp("2021-03-01"), config, target_season="2020-2021")
    assert "2020-2021" in set(during["season"].unique())

    keep = wf.training_frame_for(pool, cutoff, wf.Config(covid_mode="include"), "2021-2022")
    assert "2020-2021" in set(keep["season"].unique())


def test_downweight_halves_2020_21_weights_for_later_targets(pool):
    cutoff = pd.Timestamp("2022-01-03")
    config = wf.Config(covid_mode="downweight_0.5")
    train = wf.training_frame_for(pool, cutoff, config, "2021-2022")

    base = wf._decay_weights(train, wf.Config(covid_mode="include"), "2021-2022")
    down = wf._decay_weights(train, config, "2021-2022")
    mask = (train["season"] == "2020-2021").to_numpy()

    assert np.allclose(down[mask], base[mask] * 0.5)
    assert np.allclose(down[~mask], base[~mask])

    # and it does NOT apply when the target is 2020-21 itself
    during = wf._decay_weights(train, config, "2020-2021")
    assert np.allclose(during, base)


def test_confirmation_seasons_are_hard_refused():
    with pytest.raises(RuntimeError, match="confirmation"):
        wf.assert_seasons_allowed(["2023-2024"])

    frame = pd.DataFrame({"season": ["2023-2024"], "date": [pd.Timestamp("2024-01-01")]})
    with pytest.raises(RuntimeError, match="confirmation"):
        wf.assert_no_confirmation(frame, "test data")


def test_grid_parity_is_exact(pool):
    """The rebuilt-model path must match penaltyblog's .predict() exactly.

    Both sides run the same compiled grid with identical parameters, so this
    replaced an earlier ~1.1e-3 deviation caused by mixing the compiled fit-time
    grid with the pure-Python ``create_dixon_coles_grid`` helper.
    """
    result = wf.grid_parity(n=500, seed=7)
    assert result["n"] == 500
    assert result["max_abs_diff"] <= 1e-12, f"max abs diff {result['max_abs_diff']:.3e}"


def test_blend_arithmetic_n5_k10_is_half_and_half():
    """A team with n=5 recent matches and k=10 gets exactly 0.5*prior + 0.5*fitted."""
    fitted = {"Team": (2.0, -1.0)}
    priors = {"league_avg": (0.0, 0.0)}
    attack, defence = wf.blended_rating("Team", fitted, priors, "league_avg", n_recent=5)
    assert attack == pytest.approx(0.5 * 2.0 + 0.5 * 0.0)
    assert defence == pytest.approx(0.5 * (-1.0) + 0.5 * 0.0)


def test_blend_weight_saturates_at_k():
    fitted = {"Team": (2.0, -1.0)}
    priors = {"league_avg": (0.0, 0.0)}
    for n in (10, 11, 40):
        attack, defence = wf.blended_rating("Team", fitted, priors, "league_avg", n_recent=n)
        assert (attack, defence) == (2.0, -1.0)


def test_unseen_team_gets_the_prior_outright():
    priors = {"league_avg": (0.0, 0.0), "promoted_in": (1.5, -0.5)}
    assert wf.blended_rating("New", {}, priors, "promoted_in", n_recent=0) == (1.5, -0.5)


def test_blend_differs_between_policies_for_a_mid_weight_team():
    """The prior chosen really does change the blended rating."""
    fitted = {"Team": (2.0, -1.0)}
    priors = {"league_avg": (0.0, 0.0), "promoted_in": (1.0, -0.5)}
    avg = wf.blended_rating("Team", fitted, priors, "league_avg", n_recent=5)
    promo = wf.blended_rating("Team", fitted, priors, "promoted_in", n_recent=5)
    assert avg != promo


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