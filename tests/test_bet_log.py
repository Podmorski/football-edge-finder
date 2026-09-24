"""Tests for the bet log and closing-line value (:mod:`bet_log`).

Offline: the historical results, the Pinnacle snapshot history and ``price_match``
are all stubbed, so no file under ``data/`` is required and no credit is spent.
"""

from __future__ import annotations

import csv
import json
from datetime import date, datetime, timezone

import pandas as pd
import pytest

import bet_log
import fair_sheet as fs

SNAPSHOT = [{
    "id": "evt-1", "sport_key": "soccer_germany_bundesliga",
    "home_team": "Hoffenheim", "away_team": "Hamburger SV",
    "commence_time": "2026-10-10T13:30:00Z",
    "bookmakers": [{"key": "pinnacle", "last_update": "2026-10-10T12:00:00Z", "markets": [
        {"key": "h2h", "outcomes": [
            {"name": "Hoffenheim", "price": 1.42}, {"name": "Draw", "price": 4.76},
            {"name": "Hamburger SV", "price": 7.00}]},
        {"key": "totals", "outcomes": [
            {"name": "Over", "price": 1.92, "point": 2.5},
            {"name": "Under", "price": 1.98, "point": 2.5}]},
    ]}],
}]


@pytest.fixture
def wired(tmp_path, monkeypatch):
    """A tmp snapshot dir, a stub history and a stub closing price."""
    cache = tmp_path / "snapshots"
    cache.mkdir()
    monkeypatch.setattr(fs, "CACHE_DIR", cache)
    (cache / "evt-1__20261010T120000Z.json").write_text(
        json.dumps({"fetched_at": "2026-10-10T12:00:00+00:00", "data": SNAPSHOT}),
        encoding="utf-8")
    frame = pd.DataFrame([{
        "date": date(2026, 10, 10), "team_home": "Hoffenheim", "team_away": "Hamburger SV",
        "fthg": 3, "ftag": 1, "hthg": 1, "htag": 0,
    }])
    monkeypatch.setattr(bet_log, "_HISTORY", {"bundesliga_1": frame})
    monkeypatch.setattr(fs, "price_match", lambda slug, prices: ([{
        "market": "3+", "family": "GOAL_RANGE_FT", "fair_odds": 4.00,
        "min_acceptable": 4.14, "status": "FAIL"}, {
        "market": "1", "family": "RESULT", "fair_odds": 1.45,
        "min_acceptable": 1.50, "status": "FAIL"}], 0.0))
    return cache


def write_log(path, **overrides):
    row = {
        "date": "2026-10-10", "bookmaker": "Soccer Bet",
        "match": "Hoffenheim vs Hamburger SV",
        "market": "Full-time total goals 3+", "family": "GOAL_RANGE_FT", "code": "T:3+",
        "odds_taken": "4.20", "stake": "100", "min_acceptable": "4.19",
        "pinnacle_close": "", "result": "",
    }
    row.update(overrides)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=bet_log.FIELDS)
        writer.writeheader()
        writer.writerow(row)
    return path


# --------------------------------------------------------------------------- #
# the log file
# --------------------------------------------------------------------------- #
def test_template_has_exactly_the_agreed_columns():
    header = bet_log.TEMPLATE.read_text(encoding="utf-8").splitlines()[0]
    assert header.split(",") == bet_log.FIELDS
    assert bet_log.BET_FIELDS == bet_log.FIELDS[:9]


def test_ensure_log_creates_the_working_copy_from_the_template(tmp_path, monkeypatch):
    target = tmp_path / "bet_log.csv"
    monkeypatch.setattr(bet_log, "LOG", target)
    assert bet_log.ensure_log() == target
    assert target.read_text(encoding="utf-8").startswith("date,bookmaker,match")


def test_read_bets_rejects_a_log_without_the_bet_columns(tmp_path):
    path = tmp_path / "bad.csv"
    path.write_text("date,bookmaker\n2026-10-10,Soccer Bet\n", encoding="utf-8")
    with pytest.raises(SystemExit):
        bet_log.read_bets(path)


def test_read_bets_skips_rows_without_a_code(tmp_path):
    path = write_log(tmp_path / "log.csv")
    with path.open("a", newline="", encoding="utf-8") as handle:
        csv.writer(handle).writerow(["2026-10-11", "Soccer Bet", "A vs B", "", "", "", "", "", "", "", ""])
    assert len(bet_log.read_bets(path)) == 1


# --------------------------------------------------------------------------- #
# matching
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("text,expected", [
    ("Hoffenheim vs Hamburger SV", ("Hoffenheim", "Hamburger SV")),
    ("Schalke 04 v Elversberg", ("Schalke 04", "Elversberg")),
    ("Ajaccio - Ajaccio GFCO", ("Ajaccio", "Ajaccio GFCO")),
])
def test_split_match(text, expected):
    assert bet_log._split_match(text) == expected


def test_split_match_returns_none_for_an_unparseable_string():
    assert bet_log._split_match("HoffenheimHamburger") is None


def test_similarity_ignores_club_noise_but_keeps_real_differences():
    assert bet_log._similarity("FC Schalke 04", "Schalke") == 1.0
    assert bet_log._similarity("Hamburger SV", "Hamburger") == 1.0
    # the locked non-merge: these are different clubs
    assert bet_log._similarity("Ajaccio", "Ajaccio GFCO") < bet_log.MATCH_SIMILARITY


def test_find_result_matches_on_the_date_and_both_teams(wired):
    found = bet_log.find_result(date(2026, 10, 10), "Hoffenheim", "Hamburger SV")
    assert found is not None and found[0] == "bundesliga_1"
    assert (found[1].fthg, found[1].ftag) == (3, 1)
    assert bet_log.find_result(date(2026, 10, 10), "Hoffenheim", "Werder Bremen") is None


def test_find_result_ignores_a_match_far_outside_the_date_window(wired):
    assert bet_log.find_result(date(2026, 12, 1), "Hoffenheim", "Hamburger SV") is None


# --------------------------------------------------------------------------- #
# the closing snapshot
# --------------------------------------------------------------------------- #
def test_closing_prices_read_the_held_snapshot(wired):
    prices, fetched_at, slug = bet_log.closing_prices("Hoffenheim", "Hamburger SV", date(2026, 10, 10))
    assert slug == "bundesliga_1"
    assert fetched_at == datetime(2026, 10, 10, 12, 0, tzinfo=timezone.utc)
    assert prices["raw_1x2"] == [1.42, 4.76, 7.00]
    assert prices["line"] == 2.5


def test_closing_prices_are_none_when_no_snapshot_is_held(wired):
    assert bet_log.closing_prices("Hoffenheim", "Werder Bremen", date(2026, 10, 10)) == (None, None, None)
    assert bet_log.closing_prices("Hoffenheim", "Hamburger SV", date(2026, 10, 9))[0] is None


def test_market_index_covers_the_catalogue_and_the_ext_section():
    index = bet_log.market_index()
    assert ("RESULT", "1") in index and ("GOAL_RANGE_FT", "3+") in index
    assert ("TEAM_GOALS_HOME_FT", "HT:3+") in index     # ext-only, keeps its prefix


@pytest.mark.parametrize("family,code,expected", [
    ("GOAL_RANGE_FT", "3+", ("GOAL_RANGE_FT", "3+")),          # exactly as the sheet prints
    ("GOAL_RANGE_FT", "T:3+", ("GOAL_RANGE_FT", "3+")),        # exactly as the book prints
    ("TEAM_GOALS_HOME_FT", "HT:3+", ("TEAM_GOALS_HOME_FT", "HT:3+")),
    ("TEAM_GOALS_HOME_FT", "3+", None),                          # never guessed from a bare code
    ("GOAL_RANGE_FT", "ZZ:1", None),
])
def test_resolve_key(family, code, expected):
    assert bet_log.resolve_key(bet_log.market_index(), family, code) == expected


# --------------------------------------------------------------------------- #
# settlement, CLV and P&L
# --------------------------------------------------------------------------- #
def test_outcome_settles_a_derived_market_from_half_time_and_full_time():
    market = bet_log.market_index()[("GOAL_RANGE_FT", "3+")]
    row = pd.Series({"hthg": 1, "htag": 0, "fthg": 3, "ftag": 1})
    assert bet_log._outcome(market, row) == "W"
    assert bet_log._outcome(market, pd.Series({"hthg": 1, "htag": 0, "fthg": 1, "ftag": 1})) == "L"
    # no half-time score -> cannot settle, never guessed
    assert bet_log._outcome(market, pd.Series({"hthg": float("nan"), "htag": 0, "fthg": 3, "ftag": 1})) == ""


def test_outcome_marks_a_draw_nobet_as_void():
    market = bet_log.market_index()[("NO_BET", "XNB 1. Pol. 1")]
    assert bet_log._outcome(market, pd.Series({"hthg": 1, "htag": 1, "fthg": 2, "ftag": 1})) == "V"


@pytest.mark.parametrize("outcome,expected", [("W", 320.0), ("L", -100.0), ("V", 0.0), ("", 0.0)])
def test_pnl(outcome, expected):
    assert bet_log._pnl(outcome, 4.20, 100.0) == pytest.approx(expected)


def bet(clv, result, stake=100.0, odds=4.2):
    return {"stake": stake, "result": result, "clv": clv, "pnl": bet_log._pnl(result, odds, stake)}


def test_summary_reports_a_95_percent_interval_over_the_logged_bets():
    summary = bet_log.summarise([bet(0.02, "W"), bet(0.04, "L"), bet(0.06, "W"), bet(0.08, "L")])
    assert summary["n"] == 4 and summary["with_clv"] == 4 and summary["with_result"] == 4
    assert summary["mean_clv"] == pytest.approx(0.05)
    low, high = summary["ci"]
    assert low < 0.05 < high
    assert summary["staked"] == 400.0
    assert summary["pnl"] == pytest.approx(2 * 320.0 - 2 * 100.0)


def test_summary_without_a_closing_snapshot_still_reports_pnl():
    summary = bet_log.summarise([bet(None, "W"), bet(None, "")])
    assert summary["with_clv"] == 0 and summary["mean_clv"] is None and summary["ci"] is None


def test_summary_needs_two_points_before_it_shows_an_interval():
    assert bet_log.summarise([bet(0.03, "W")])["ci"] is None


# --------------------------------------------------------------------------- #
# end to end
# --------------------------------------------------------------------------- #
def test_log_close_fills_the_closing_price_and_result(tmp_path, wired, capsys):
    path = write_log(tmp_path / "data" / "bet_log.csv")
    assert bet_log.main(str(path)) == 0

    rows = list(csv.DictReader(path.open(newline="", encoding="utf-8")))
    assert rows[0]["pinnacle_close"] == "4.0000"
    assert rows[0]["result"] == "W"

    out = capsys.readouterr().out
    assert "filled: results 1/1, closing prices 1/1" in out
    assert "mean CLV +0.0500" in out
    assert "P&L +320.00 on 100.00 staked (ROI +320.00%)" in out
    assert "DECISION RULE: no conclusion before 50 logged bets" in out
    assert "49 more bet(s) needed" in out


def test_log_close_flags_a_bet_below_the_minimum_acceptable_odds(tmp_path, wired, capsys):
    path = write_log(tmp_path / "bet_log.csv", odds_taken="4.00", min_acceptable="4.19")
    bet_log.main(str(path))
    assert "WARNING: 1 bet(s) taken below the logged minimum acceptable odds" in capsys.readouterr().out


def test_log_close_reports_a_match_it_cannot_find(tmp_path, wired, capsys):
    path = write_log(tmp_path / "bet_log.csv", match="Ajaccio vs Ajaccio GFCO", date="2026-10-10")
    bet_log.main(str(path))
    out = capsys.readouterr().out
    assert "no result found: 1" in out and "no pre-kickoff snapshot: 1" in out


def test_log_close_reports_an_unknown_market(tmp_path, wired, capsys):
    path = write_log(tmp_path / "bet_log.csv", family="NOT_A_FAMILY", code="ZZ:1")
    bet_log.main(str(path))
    assert "market not in the catalogue: 1" in capsys.readouterr().out