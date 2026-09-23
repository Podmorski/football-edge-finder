"""Tests for locked split access.

These are hermetic: they use a temporary config, a temporary data dir, and a
temporary access log, so no real confirmation data is read and the real
``research/confirmation_access.csv`` is never touched.
"""

from __future__ import annotations

import pandas as pd
import pytest

from core import splits

CONFIG_TEXT = """
splits:
  warmup:
    seasons: ["2015-2016"]
    locked: false
  confirmation:
    seasons: ["2023-2024"]
    locked: true
"""


@pytest.fixture
def fake_env(tmp_path):
    config_path = tmp_path / "splits.yaml"
    config_path.write_text(CONFIG_TEXT, encoding="utf-8")

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    frame = pd.DataFrame(
        {
            "id": ["fake-1"],
            "season": ["2023-2024"],
            "date": pd.to_datetime(["2024-01-01"]),
            "team_home": ["A"],
            "team_away": ["B"],
            "fthg": [2],
            "ftag": [1],
        }
    ).set_index("id")
    frame.to_parquet(data_dir / "fake_league.parquet")

    access_log = tmp_path / "confirmation_access.csv"
    return config_path, data_dir, access_log


def test_unknown_split_raises(fake_env):
    config_path, data_dir, access_log = fake_env
    with pytest.raises(KeyError):
        splits.load_split(
            "nope", config_path=config_path, data_dir=data_dir, access_log_path=access_log
        )


def test_confirmation_refused_without_confirm(fake_env):
    config_path, data_dir, access_log = fake_env
    with pytest.raises(splits.ConfirmationLockedError):
        splits.load_split(
            "confirmation",
            config_path=config_path,
            data_dir=data_dir,
            access_log_path=access_log,
            leagues=["fake_league"],
        )
    assert not access_log.exists(), "a refused read must not log an access"


def test_confirmation_refused_without_reason(fake_env):
    config_path, data_dir, access_log = fake_env
    with pytest.raises(ValueError):
        splits.load_split(
            "confirmation",
            confirm=True,
            reason=None,
            config_path=config_path,
            data_dir=data_dir,
            access_log_path=access_log,
            leagues=["fake_league"],
        )
    assert not access_log.exists()


def test_confirmation_refused_with_blank_reason(fake_env):
    config_path, data_dir, access_log = fake_env
    with pytest.raises(ValueError):
        splits.load_split(
            "confirmation",
            confirm=True,
            reason="   ",
            config_path=config_path,
            data_dir=data_dir,
            access_log_path=access_log,
            leagues=["fake_league"],
        )
    assert not access_log.exists()


def test_confirmation_with_confirm_and_reason_loads_and_logs(fake_env):
    config_path, data_dir, access_log = fake_env
    df = splits.load_split(
        "confirmation",
        confirm=True,
        reason="unit test",
        config_path=config_path,
        data_dir=data_dir,
        access_log_path=access_log,
        leagues=["fake_league"],
    )
    assert len(df) == 1
    assert df["league"].iloc[0] == "fake_league"

    assert access_log.exists()
    logged = access_log.read_text(encoding="utf-8").strip().splitlines()
    assert len(logged) == 2  # header + one access
    assert "unit test" in logged[1]


def test_unlocked_split_needs_no_confirmation_and_does_not_log(fake_env):
    config_path, data_dir, access_log = fake_env
    df = splits.load_split(
        "warmup",
        config_path=config_path,
        data_dir=data_dir,
        access_log_path=access_log,
        leagues=["fake_league"],
    )
    assert isinstance(df, pd.DataFrame)
    assert not access_log.exists()