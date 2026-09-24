"""Mozzart↔PS3838 coverage record, the gap check and the PS3838 snapshot cache."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import coverage
import health
import ps3838_odds


def _event():
    return {"eventId": "1", "home": "a", "away": "b",
            "startTime": "2099-01-01T12:00:00Z", "markets": []}


def test_gaps_flag_only_the_no_mozzart_leagues(tmp_path, monkeypatch):
    monkeypatch.setattr(coverage, "PATH", tmp_path / "coverage.json")
    coverage.write({date(2026, 9, 26)}, {
        "eng_league_two": {"ps3838": 10, "mozzart": 0, "joined": 0},   # gap
        "esp_segunda": {"ps3838": 10, "mozzart": 6, "joined": 5},      # Mozzart is there
        "league_one_t3": {"ps3838": 2, "mozzart": 0, "joined": 0},     # below the >= 3 threshold
        "ger_liga3": {"ps3838": 1, "mozzart": 0, "joined": 0},        # below the threshold
    })
    assert coverage.gaps() == [("eng_league_two", 10)]


def test_a_stale_record_is_not_trusted(tmp_path, monkeypatch):
    monkeypatch.setattr(coverage, "PATH", tmp_path / "coverage.json")
    old = datetime.now(timezone.utc) - timedelta(hours=coverage.STALE_HOURS + 1)
    coverage.write({date(2026, 9, 26)},
                   {"eng_league_two": {"ps3838": 10, "mozzart": 0, "joined": 0}},
                   when=old)
    assert coverage.gaps() == []
    assert coverage.zero_joins() == 0
    assert coverage.load()["leagues"]["eng_league_two"]["ps3838"] == 10


def test_health_puts_the_gap_banner_at_the_top(tmp_path, monkeypatch):
    monkeypatch.setattr(coverage, "PATH", tmp_path / "coverage.json")
    coverage.write({date(2026, 9, 26)}, {
        "esp_segunda": {"ps3838": 10, "mozzart": 0, "joined": 0},
        "eng_premier": {"ps3838": 8, "mozzart": 8, "joined": 7},
    })
    out = tmp_path / "health.md"
    monkeypatch.setattr(health, "OUT", out)
    monkeypatch.setattr(health, "SCHEDULER_LOG", tmp_path / "none.log")
    monkeypatch.setattr(health, "PAPER_LOG", tmp_path / "none.csv")
    assert health.write() == 0
    text = out.read_text(encoding="utf-8")
    assert text.splitlines()[0] == "# Health"
    assert "MOZZART COVERAGE GAP" in text
    assert "esp_segunda: PS3838 10 match(es)" in text
    assert "eng_premier" not in text.split("## Last run")[0]


def test_health_leads_with_zero_joins_when_nothing_joined(tmp_path, monkeypatch):
    monkeypatch.setattr(coverage, "PATH", tmp_path / "coverage.json")
    coverage.write({date(2026, 9, 26)}, {
        "eng_league_two": {"ps3838": 10, "mozzart": 0, "joined": 0},
        "esp_segunda": {"ps3838": 5, "mozzart": 0, "joined": 0},
    })
    out = tmp_path / "health.md"
    monkeypatch.setattr(health, "OUT", out)
    monkeypatch.setattr(health, "SCHEDULER_LOG", tmp_path / "none.log")
    monkeypatch.setattr(health, "PAPER_LOG", tmp_path / "none.csv")
    assert health.write() == 0
    text = out.read_text(encoding="utf-8")
    assert "ZERO JOINS" in text
    assert text.index("ZERO JOINS") < text.index("MOZZART COVERAGE GAP")


def test_fetch_league_reuses_a_fresh_snapshot(tmp_path, monkeypatch):
    monkeypatch.setattr(ps3838_odds, "CACHE_DIR", tmp_path)
    calls = []
    monkeypatch.setattr(ps3838_odds, "_get",
                        lambda *a, **k: calls.append(1) or {"events": [_event()]})

    first, _ = ps3838_odds.fetch_league(object(), "k", "eng_premier")
    assert len(calls) == 1
    again, _ = ps3838_odds.fetch_league(object(), "k", "eng_premier", max_age_minutes=60)
    assert len(calls) == 1 and again == first          # served from the cache
    ps3838_odds.fetch_league(object(), "k", "eng_premier")   # max_age=None forces a fetch
    assert len(calls) == 2