"""Paper trading: record, close, settle and report — never a real bet."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

import paper_trade


def flag(**overrides) -> dict:
    base = {
        "kickoff": "2026-09-26T13:00:00Z", "league": "bundesliga_1",
        "home": "Bayern", "away": "Dortmund", "family": "RESULT", "section": "Konačan ishod",
        "code": "1", "meaning": "home win", "mozzart_odds": 2.10, "fair_odds": 2.00,
        "min_acceptable": 2.07, "ev": 0.05, "stale": False,
        "mozzart_snapshot": "2026-09-26T12:10:00Z", "pinnacle_snapshot": "2026-09-26T12:00:00Z",
    }
    base.update(overrides)
    return base


@pytest.fixture
def log(tmp_path, monkeypatch):
    monkeypatch.setattr(paper_trade, "LOG", tmp_path / "paper_bets.csv")
    return paper_trade.LOG


def test_record_appends_once_and_dedups(log):
    assert paper_trade.record([flag()]) == 1
    assert paper_trade.record([flag()]) == 0          # same match + market
    assert paper_trade.record([flag(code="X")]) == 1  # a different market
    rows = paper_trade.read_rows()
    assert len(rows) == 2
    assert rows[0]["stake"] == "1.00"


def test_close_fills_the_de_margined_pinnacle_close(log, monkeypatch):
    paper_trade.record([flag()])
    kickoff = datetime(2026, 9, 26, 13, 0, tzinfo=timezone.utc)
    now = kickoff - timedelta(minutes=10)
    event = {"id": "E1", "home_team": "Bayern", "away_team": "Dortmund",
             "commence_time": "2026-09-26T13:00:00Z",
             "sport_key": "soccer_germany_bundesliga"}
    monkeypatch.setattr(paper_trade.fs, "upcoming_events",
                        lambda s, k, w: ([("soccer_germany_bundesliga", event)], {}, 0))
    monkeypatch.setattr(paper_trade.fs, "fetch_snapshot",
                        lambda s, k, sk, e: ({"x": 1}, 2, "api", 400))
    monkeypatch.setattr(paper_trade.fs, "pinnacle_prices",
                        lambda e, s: {"snapshot": "2026-09-26T12:55:00Z"})
    monkeypatch.setattr(paper_trade.fs, "price_match",
                        lambda slug, prices: ([{"family": "RESULT", "market": "1",
                                               "fair_odds": 2.0}], 0.0))
    monkeypatch.setattr(paper_trade.bet_log, "market_index",
                        lambda: {("RESULT", "1"): object()})
    assert paper_trade.close(now, session=object(), key="k") == 1
    row = paper_trade.read_rows()[0]
    assert row["pinnacle_close"] == "2.0000"
    assert float(row["clv"]) == pytest.approx(2.10 / 2.0 - 1.0)


def test_close_does_nothing_outside_the_window(log, monkeypatch):
    paper_trade.record([flag()])
    kickoff = datetime(2026, 9, 26, 13, 0, tzinfo=timezone.utc)
    called = []
    monkeypatch.setattr(paper_trade.fs, "upcoming_events",
                        lambda *a: called.append(1) or ([], {}, 0))
    assert paper_trade.close(kickoff - timedelta(hours=3), session=object(), key="k") == 0
    assert called == []          # no Odds API call when nothing is in the window


class _Market:
    def outcome(self, hth, hta, fth, fta):
        return "win" if fth > fta else "lose"


def test_settle_uses_the_section_aware_settlement(log, monkeypatch):
    paper_trade.record([flag()])
    kickoff = datetime(2026, 9, 26, 13, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(paper_trade.bet_log, "market_index",
                        lambda: {("RESULT", "1"): _Market()})
    monkeypatch.setattr(paper_trade.bet_log, "find_result",
                        lambda when, home, away: ("bundesliga_1",
                                                  type("R", (), {"hthg": 1, "htag": 0,
                                                                 "fthg": 2, "ftag": 0})(),
                                                  1.0, 1.0))
    assert paper_trade.settle(kickoff + timedelta(hours=4)) == 1
    row = paper_trade.read_rows()[0]
    assert row["result"] == "W"
    assert float(row["pnl"]) == pytest.approx(1.10)


def test_settle_waits_until_the_match_is_over(log, monkeypatch):
    paper_trade.record([flag()])
    kickoff = datetime(2026, 9, 26, 13, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(paper_trade.bet_log, "market_index",
                        lambda: {("RESULT", "1"): _Market()})
    assert paper_trade.settle(kickoff + timedelta(minutes=30)) == 0


def test_report_runs_with_no_bets(log, capsys):
    assert paper_trade.report() == 0
    assert "No paper bets yet" in capsys.readouterr().out


def test_report_prints_clv_and_pnl(log, capsys):
    paper_trade.record([flag()])
    rows = paper_trade.read_rows()
    rows[0]["clv"] = "0.05"
    rows[0]["result"] = "W"
    rows[0]["pnl"] = "1.10"
    paper_trade.write_rows(rows)
    assert paper_trade.report() == 0
    out = capsys.readouterr().out
    assert "mean CLV" in out and "virtual P&L" in out
    assert "NEVER place bets automatically" in out