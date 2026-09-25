"""The hard caps: the guard refuses on the session cap, the monthly cap and the reserve."""

from __future__ import annotations

import pytest

import api_guard
import mozzart_odds


def test_session_cap_refuses_after_the_cap(monkeypatch):
    monkeypatch.setattr(api_guard, "monthly_used", lambda provider: 0)
    api_guard.start_session(2)
    assert api_guard.check("pulsescore")[0] is True
    api_guard.note("pulsescore")
    api_guard.note("pulsescore")
    allowed, reason = api_guard.check("pulsescore")
    assert allowed is False and "session cap 2" in reason


def test_monthly_cap_refuses(monkeypatch):
    monkeypatch.setattr(api_guard, "monthly_used", lambda provider: 400)
    api_guard.start_session(10)
    allowed, reason = api_guard.check("pulsescore")
    assert allowed is False and "monthly cap 400" in reason


def test_reserve_refuses(monkeypatch):
    monkeypatch.setattr(api_guard, "monthly_used", lambda provider: 360)
    api_guard.start_session(10)
    allowed, reason = api_guard.check("pulsescore")
    assert allowed is False and "stop threshold 50" in reason


def test_free_odds_api_calls_do_not_eat_the_cap(monkeypatch):
    monkeypatch.setattr(api_guard, "monthly_used", lambda provider: 0)
    api_guard.start_session(1)
    api_guard.note("odds_api", 0)                 # a free events call
    assert api_guard.check("odds_api")[0] is True
    api_guard.note("odds_api", 1)                 # a billable call
    assert api_guard.check("odds_api")[0] is False


def test_the_default_session_cap_is_the_adhoc_cap():
    api_guard.start_session()
    assert api_guard.session_cap() == api_guard.SESSION_CAP_DEFAULT


def test_refusals_are_logged(tmp_path, monkeypatch):
    monkeypatch.setattr(api_guard, "LOG_DIR", tmp_path)
    monkeypatch.setattr(api_guard, "REFUSAL_LOG", tmp_path / "refusals.csv")
    api_guard.refuse("pulsescore", "session cap 10 reached", "mozzart global events p1")
    rows = api_guard.read_refusals()
    assert rows and rows[0]["provider"] == "pulsescore"
    assert rows[0]["reason"] == "session cap 10 reached"


def test_a_feed_refuses_when_the_guard_says_no(monkeypatch):
    monkeypatch.setattr(api_guard, "check", lambda provider: (False, "session cap 0 reached"))
    monkeypatch.setattr(api_guard, "refuse", lambda *a, **k: None)
    with pytest.raises(RuntimeError, match="session cap 0"):
        mozzart_odds._get(object(), "k", "/soccer/events")
