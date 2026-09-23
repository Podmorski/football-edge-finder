"""Sanity checks for the League One Dixon-Coles model.

These are correctness checks, not performance gates. The model is fitted once
per session and shared.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from models import league_one_dixon_coles as m


@pytest.fixture(scope="module")
def ctx():
    matches = m.load_matches()
    train = m.training_frame(matches)
    holdout = m.holdout_frame(matches)

    eligible = m.eligible_teams(train)
    ok = holdout["team_home"].isin(eligible) & holdout["team_away"].isin(eligible)
    remaining = holdout[ok].reset_index(drop=True)

    model, _ = m.fit(train)
    return {
        "model": model,
        "train": train,
        "remaining": remaining,
        "holdout_grids": m.grids_for(model, remaining),
        "train_grids": m.grids_for(model, train),
    }


def test_grid_mass_within_001_of_1(ctx):
    masses = np.array([g.grid.sum() for g in ctx["holdout_grids"]])
    truncation_loss = 1.0 - masses.mean()
    assert abs(truncation_loss) <= 0.01, (
        f"grid truncation loss {truncation_loss:.6f} exceeds 0.01"
    )


def test_1x2_probabilities_sum_to_1(ctx):
    trio = np.array([[g.home_win, g.draw, g.away_win] for g in ctx["holdout_grids"]])
    assert np.allclose(trio.sum(axis=1), 1.0, atol=1e-6)


def test_over_under_25_sums_to_1(ctx):
    for g in ctx["holdout_grids"]:
        total = g.total_goals("over", 2.5) + g.total_goals("under", 2.5)
        assert abs(total - 1.0) < 1e-9


def test_btts_sums_to_1(ctx):
    for g in ctx["holdout_grids"]:
        assert abs((g.btts_yes + g.btts_no) - 1.0) < 1e-9


def test_training_mean_goals_gap_under_015(ctx):
    pairs = np.array([m.expected_goals(g) for g in ctx["train_grids"]])
    train = ctx["train"]
    gap_home = abs(pairs[:, 0].mean() - train["fthg"].mean())
    gap_away = abs(pairs[:, 1].mean() - train["ftag"].mean())
    assert gap_home <= 0.15, f"home goals gap {gap_home:.3f} > 0.15"
    assert gap_away <= 0.15, f"away goals gap {gap_away:.3f} > 0.15"


def test_home_advantage_positive(ctx):
    assert ctx["model"].get_params()["home_advantage"] > 0


def test_rho_in_expected_range(ctx):
    rho = ctx["model"].get_params()["rho"]
    assert -0.3 <= rho <= 0.1, f"rho {rho:.4f} outside [-0.3, 0.1]"


def test_spearman_attack_defence_vs_final_table(ctx):
    model = ctx["model"]
    train = ctx["train"]
    params = model.get_params()
    attack = np.array([params[f"attack_{t}"] for t in model.teams])
    defence = np.array([params[f"defence_{t}"] for t in model.teams])
    strength = dict(zip(model.teams, attack - defence))

    table = m.final_table_points(train, m.RECENT_TRAIN_SEASONS[-1])
    pair = [(strength[t], table[t]) for t in table.index if t in strength]
    a = pd.Series([p[0] for p in pair])
    b = pd.Series([p[1] for p in pair])
    rho = m.spearman(a, b)
    assert rho > 0.5, f"Spearman {rho:.3f} is not positive enough"