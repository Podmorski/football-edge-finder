"""Global Mozzart feed: label filtering, the window stop, cache reuse, zero-joins."""

from __future__ import annotations

from datetime import date, datetime, timezone

import coverage
import mozzart_odds


def _event(label: str, kickoff: str, event_id: str = "1") -> dict:
    return {"eventId": event_id, "home": "A", "away": "B", "league": label,
            "startTime": kickoff, "markets": []}


def test_fetch_events_filters_by_label_and_stamps_the_slug(monkeypatch):
    events = [
        _event("Engleska 4", "2026-09-26T14:00:00.000Z", "1"),
        _event("Engleska 3", "2026-09-26T14:00:00.000Z", "2"),
        _event("Liga nacija (A) - Evropa", "2026-09-26T14:00:00.000Z", "3"),
    ]
    monkeypatch.setattr(mozzart_odds, "fetch_global_events",
                        lambda *a, **k: (events, datetime.now(timezone.utc)))
    out = mozzart_odds.fetch_events(object(), "k", {"eng_league_two"})
    assert [event["eventId"] for event in out] == ["1"]
    assert out[0]["_slug"] == "eng_league_two"
    assert out[0]["_fetched_at"]


def test_global_feed_stops_at_until_and_reuses_the_cache(monkeypatch, tmp_path):
    monkeypatch.setattr(mozzart_odds, "EVENTS_CACHE", tmp_path / "g.json")
    monkeypatch.setattr(mozzart_odds, "FEED_STATS", tmp_path / "feed.json")
    pages = {
        1: {"totalPages": 3, "events": [
            _event("Engleska 4", "2026-09-25T12:00:00.000Z", "1"),
            _event("Engleska 4", "2026-09-26T12:00:00.000Z", "2")]},
        2: {"totalPages": 3, "events": [
            _event("Engleska 4", "2026-09-28T12:00:00.000Z", "3")]},
        3: {"totalPages": 3, "events": []},
    }
    calls: list[int] = []

    def fake_get(session, key, path, params=None, note=""):
        calls.append(params["page"])
        return pages[params["page"]]

    monkeypatch.setattr(mozzart_odds, "_get", fake_get)
    until = datetime(2026, 9, 27, tzinfo=timezone.utc)
    events, _ = mozzart_odds.fetch_global_events(object(), "k", until=until,
                                                 max_age_minutes=0)
    assert [event["eventId"] for event in events] == ["1", "2"]
    assert calls == [1, 2]                       # stopped on the page that crossed `until`

    calls.clear()
    again, _ = mozzart_odds.fetch_global_events(object(), "k", until=until,
                                                max_age_minutes=60)
    assert again == events and calls == []       # a fresh cache costs no request

    # A window that reaches further than the cache forces a refetch.
    later = datetime(2026, 9, 30, tzinfo=timezone.utc)
    mozzart_odds.fetch_global_events(object(), "k", until=later, max_age_minutes=60)
    assert calls == [1, 2, 3]


def test_gap_threshold_is_three(monkeypatch, tmp_path):
    monkeypatch.setattr(coverage, "PATH", tmp_path / "c.json")
    coverage.write({date(2026, 9, 26)}, {
        "three": {"ps3838": 3, "mozzart": 0, "joined": 0},   # at the threshold
        "two": {"ps3838": 2, "mozzart": 0, "joined": 0},     # below it
    })
    assert coverage.gaps() == [("three", 3)]


def test_zero_joins_fires_only_when_nothing_joined(monkeypatch, tmp_path):
    monkeypatch.setattr(coverage, "PATH", tmp_path / "c.json")
    coverage.write({date(2026, 9, 26)}, {
        "eng_league_two": {"ps3838": 10, "mozzart": 0, "joined": 0},
        "esp_segunda": {"ps3838": 5, "mozzart": 5, "joined": 0},
    })
    assert coverage.zero_joins() == 15           # PS3838 priced 15, joined none

    coverage.write({date(2026, 9, 26)}, {
        "eng_league_two": {"ps3838": 10, "mozzart": 10, "joined": 8},
    })
    assert coverage.zero_joins() == 0

    coverage.write({date(2026, 9, 26)}, {
        "small": {"ps3838": 4, "mozzart": 0, "joined": 0},
    })
    assert coverage.zero_joins() == 0            # below the >= 5 floor
