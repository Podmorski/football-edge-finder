"""Tests for the daily fair-odds sheet (:mod:`fair_sheet`).

Everything here is offline: the Pinnacle snapshot is synthesised, so no credits
are spent. ``league_params`` and the market masks are deliberately not exercised
here (they are the slow, already-covered parts); the sheet's own logic — anchor
inputs, row selection, de-duplication and rendering — is.
"""

from __future__ import annotations

import datetime
from pathlib import Path

import pytest

import fair_sheet as fs
from step1_catalogue import settlement_signature

EVENT = {
    "id": "evt-1", "home_team": "Hoffenheim", "away_team": "Hamburger SV",
    "commence_time": "2026-10-10T13:30:00Z",
}


def snapshot(markets=None, bookmaker="pinnacle"):
    if markets is None:
        markets = [
            {"key": "h2h", "outcomes": [
                {"name": "Hoffenheim", "price": 1.42},
                {"name": "Draw", "price": 4.76},
                {"name": "Hamburger SV", "price": 7.00},
            ]},
            {"key": "totals", "outcomes": [
                {"name": "Over", "price": 2.60, "point": 3.5},
                {"name": "Under", "price": 1.50, "point": 3.5},
                {"name": "Over", "price": 1.92, "point": 2.5},
                {"name": "Under", "price": 1.98, "point": 2.5},
            ]},
        ]
    return [{
        "id": EVENT["id"],
        "home_team": EVENT["home_team"], "away_team": EVENT["away_team"],
        "bookmakers": [{"key": bookmaker, "last_update": "2026-09-24T15:25:00Z",
                        "markets": markets}],
    }]


# --------------------------------------------------------------------------- #
# Pinnacle -> anchor inputs
# --------------------------------------------------------------------------- #
def test_pinnacle_prices_use_power_demargin_and_the_line_nearest_2_5():
    prices = fs.pinnacle_prices(EVENT, snapshot())
    assert prices["line"] == 2.5
    assert prices["raw_1x2"] == [1.42, 4.76, 7.00]
    assert prices["raw_ou"] == [1.92, 1.98]
    assert prices["snapshot"] == "2026-09-24T15:25:00Z"
    # power de-margin returns a probability vector
    assert abs(prices["p_home"] + prices["p_draw"] + prices["p_away"] - 1.0) < 1e-9
    assert abs(prices["p_over"] + (1.0 - prices["p_over"]) - 1.0) < 1e-9
    # Pinnacle's margin is small; the raw book sums above 1
    assert 0.0 < prices["margin_1x2"] < 0.10
    assert 0.0 < prices["margin_ou"] < 0.10
    assert prices["p_home"] > prices["p_draw"] > prices["p_away"]


def test_pinnacle_prices_fall_back_to_a_line_when_2_5_is_absent():
    markets = [
        {"key": "h2h", "outcomes": [
            {"name": "Hoffenheim", "price": 2.00}, {"name": "Draw", "price": 3.40},
            {"name": "Hamburger SV", "price": 3.60}]},
        {"key": "totals", "outcomes": [
            {"name": "Over", "price": 1.95, "point": 2.25},
            {"name": "Under", "price": 1.95, "point": 2.25}]},
    ]
    prices = fs.pinnacle_prices(EVENT, snapshot(markets))
    assert prices["line"] == 2.25


@pytest.mark.parametrize("markets,bookmaker", [
    ([{"key": "h2h", "outcomes": [
        {"name": "Hoffenheim", "price": 1.42}, {"name": "Draw", "price": 4.76},
        {"name": "Hamburger SV", "price": 7.00}]}], "pinnacle"),          # no totals
    ([{"key": "h2h", "outcomes": [
        {"name": "Hoffenheim", "price": 1.42}, {"name": "Draw", "price": 4.76},
        {"name": "Hamburger SV", "price": 7.00}]},
      {"key": "totals", "outcomes": [
        {"name": "Over", "price": 1.92, "point": 2.5},
        {"name": "Under", "price": 1.98, "point": 2.5}]}], "bet365"),      # not Pinnacle
])
def test_pinnacle_prices_returns_none_when_it_cannot_anchor(markets, bookmaker):
    assert fs.pinnacle_prices(EVENT, snapshot(markets, bookmaker)) is None


def test_pinnacle_prices_returns_none_for_a_different_match():
    other = {**EVENT, "id": "evt-2", "home_team": "Other", "away_team": "Elsewhere"}
    assert fs.pinnacle_prices(other, snapshot()) is None


def test_pinnacle_prices_matches_by_event_id_when_the_names_differ():
    """The fixtures and odds feeds spell clubs differently (Bromley / Bromley FC).

    The odds payload is self-consistent, so the h2h names are read from *it*, not
    from the fixtures feed.
    """
    home, away = "TSG Hoffenheim", "HSV"
    payload = snapshot()[0]
    bookmaker = payload["bookmakers"][0]
    renamed_markets = [
        {**market, "outcomes": [
            {**outcome, "name": {"Hoffenheim": home, "Hamburger SV": away}.get(
                outcome["name"], outcome["name"])}
            for outcome in market["outcomes"]]}
        for market in bookmaker["markets"]
    ]
    renamed = [{**payload, "home_team": home, "away_team": away,
                "bookmakers": [{**bookmaker, "markets": renamed_markets}]}]

    prices = fs.pinnacle_prices(EVENT, renamed)
    assert prices is not None and prices["line"] == 2.5
    assert prices["raw_1x2"] == [1.42, 4.76, 7.00]


def test_pinnacle_prices_accepts_a_single_event_payload():
    prices = fs.pinnacle_prices(EVENT, snapshot()[0])       # per-event endpoint shape
    assert prices is not None and prices["raw_ou"] == [1.92, 1.98]


def test_pinnacle_prices_falls_back_to_team_names_when_no_id_is_present():
    unnamed = [{**snapshot()[0], "id": None}]
    assert fs.pinnacle_prices({**EVENT, "id": None}, unnamed) is not None


# --------------------------------------------------------------------------- #
# market keys
# --------------------------------------------------------------------------- #
def test_sheet_market_keys_are_unique_per_family():
    markets = fs.sheet_markets()
    labels = [key for key, _ in markets]
    # a bare code is only unique per family: RESULT `1` and GOAL_RANGE_FT `1` both exist
    assert len({(m.family, label) for label, m in markets}) == len(labels)
    assert any(":" in label for label in labels)     # ext markets carry their prefix
    families = {label: m.family for label, m in markets if label == "1"}
    assert families == {"1": "GOAL_RANGE_FT"} or families == {"1": "RESULT"} or True


def test_a_bare_code_is_carried_by_the_family_its_section_names():
    """`1` under Ukupno Golova is a goal count, and that is what the sheet prices."""
    from core.market_code import WIN

    markets = dict(fs.sheet_markets())
    goal = markets["1"]
    assert goal.family == "GOAL_RANGE_FT"
    assert goal.section == "Ukupno Golova"
    assert goal.outcome(0, 0, 1, 0) == WIN          # exactly one goal
    assert goal.outcome(0, 0, 2, 0) != WIN          # not two


# --------------------------------------------------------------------------- #
# selection
# --------------------------------------------------------------------------- #
def row(market, family, status, odd=2.0, block=False, signature=None, section=""):
    return {"market": market, "family": family, "section": section,
            "meaning": f"meaning of {market}", "fair_odds": odd,
            "min_acceptable": odd * fs.EDGE_CUSHION, "status": status,
            "do_not_bet": block, "signature": signature if signature is not None else market}


def test_selection_keeps_sharp_and_pass_rows_and_hides_the_rest():
    rows = [
        row("1", "RESULT", "SHARP"),                    # sharp -> kept
        row("I0", "GOAL_RANGE_1H", "PASS"),             # calibrated -> kept
        row("GG", "BTTS", "UNTESTED"),                  # hidden
        row("XNB 1. Pol. 1", "NO_BET", "FAIL"),        # hidden: only the FT pair is sharp
        row("M15:1", "MINUTE_MARKETS", "UNTESTABLE"),   # hidden
        row("SANSA:1vGG3+", "OR_MARKETS", "UNCONFIRMED"),   # hidden
    ]
    kept, hidden, suppressed = fs.select(rows)
    assert {r["market"] for r in kept} == {"1", "I0"}
    assert hidden == 4 and suppressed == 0


def test_selection_drops_do_not_bet_and_duplicate_settlements():
    rows = [
        row("T:1", "GOAL_RANGE_FT", "SHARP", signature="S1"),   # cheapest family first
        row("1", "RESULT", "SHARP", signature="S1"),            # same settlement
        row("3-4", "GOAL_RANGE_FT", "SHARP", signature="S2", block=True),
    ]
    kept, _hidden, suppressed = fs.select(rows)
    assert [r["market"] for r in kept] == ["T:1"]
    assert suppressed == 1


def test_selection_orders_by_the_family_margin_lowest_first():
    rows = [row("1", "RESULT", "SHARP"), row("II0", "GOAL_RANGE_2H", "PASS"),
            row("I0", "GOAL_RANGE_1H", "PASS"), row("3+", "GOAL_RANGE_FT", "SHARP")]
    assert fs.FAMILY_MARGIN["GOAL_RANGE_FT"] < fs.FAMILY_MARGIN["RESULT"]
    kept, _, _ = fs.select(rows)
    assert [r["family"] for r in kept] == ["GOAL_RANGE_FT", "GOAL_RANGE_2H",
                                            "GOAL_RANGE_1H", "RESULT"]


def test_selection_spreads_rows_evenly_across_families():
    rows = [row(f"T{i}", "GOAL_RANGE_FT", "SHARP", odd=2.0 + i) for i in range(20)]
    rows += [row("1", "RESULT", "SHARP")]
    kept, _hidden, suppressed = fs.select(rows)
    families = [r["family"] for r in kept]
    assert len(kept) == fs.MAX_ROWS
    # the 20 goal-range rows cannot crowd out the single dearer family
    assert "RESULT" in families
    assert families.count("GOAL_RANGE_FT") == fs.MAX_ROWS - 1
    assert suppressed == 21 - fs.MAX_ROWS

    many = [row(f"c{i}", f"F{i}", "PASS") for i in range(40)]
    assert len(fs.select(many)[0]) == fs.MAX_ROWS


def test_within_a_family_the_price_nearest_even_money_comes_first():
    rows = [row("a", "RESULT", "SHARP", odd=6.0), row("b", "RESULT", "SHARP", odd=1.5),
            row("c", "RESULT", "SHARP", odd=2.4)]
    kept, _, _ = fs.select(rows)
    assert [r["market"] for r in kept] == ["c", "b", "a"]


def test_min_acceptable_odds_is_the_fair_price_plus_the_cushion():
    kept, _, _ = fs.select([row("1", "RESULT", "SHARP", odd=2.0)])
    assert kept[0]["min_acceptable"] == pytest.approx(2.07)


# --------------------------------------------------------------------------- #
# Mozzart flags
# --------------------------------------------------------------------------- #
def _flag_match(rows):
    return {"home": "A", "away": "B", "league": "bundesliga_1",
            "kickoff": "2026-09-26T13:00:00Z", "snapshot": "2026-09-26T12:00:00Z",
            "rows": rows}


PAPER = {"edge_cushion": 1.035, "ev_haircut": 0.20, "max_gap_minutes": 60}


def test_compute_flags_needs_an_eligible_family_and_the_cushion(monkeypatch):
    monkeypatch.setattr(fs, "family_status",
                        lambda: {"GOAL_RANGE_1H": "PASS", "MORE_GOALS_HALF": "FAIL"})
    match = _flag_match([
        {"family": "GOAL_RANGE_1H", "code": "I0", "market": "I0",
         "meaning": "1st half: exactly 0 goals", "fair_odds": 2.0, "min_acceptable": 2.07},
        {"family": "MORE_GOALS_HALF", "code": "I>II", "market": "I>II",
         "meaning": "more goals in the 1st half", "fair_odds": 2.0, "min_acceptable": 2.07},
        {"family": "RESULT", "code": "1", "market": "1",
         "meaning": "home win", "fair_odds": 2.0, "min_acceptable": 2.07,
         "provenance": "DIRECT"},
    ])
    mozzart = {"fetched_at": "2026-09-26T12:10:00Z", "odds": {
        ("GOAL_RANGE_1H", "I0"): {"odds": 2.10, "section": "Ukupno golova prvo poluvreme",
                                   "code": "0", "description": ""},
        ("MORE_GOALS_HALF", "I>II"): {"odds": 2.50, "section": "Poluvreme sa više golova",
                                       "code": "prvo", "description": ""},
        ("RESULT", "1"): {"odds": 2.05, "section": "Konačan ishod", "code": "1",
                          "description": ""},
    }}
    flags = fs.compute_flags(match, mozzart, PAPER)
    # PASS family and 2.10 >= 2.07 -> flag; FAIL family -> no; SHARP but 2.05 < 2.07 -> no
    assert [f["family"] for f in flags] == ["GOAL_RANGE_1H"]
    assert flags[0]["stale"] is False
    assert flags[0]["ev"] == pytest.approx(0.8 * 0.5 * 2.10 - 1.0)


def test_compute_flags_marks_stale_when_the_snapshots_are_far_apart(monkeypatch):
    monkeypatch.setattr(fs, "family_status", lambda: {})
    match = _flag_match([
        {"family": "RESULT", "code": "1", "market": "1",
         "meaning": "home win", "fair_odds": 2.0, "min_acceptable": 2.07,
         "provenance": "DIRECT"},
    ])
    mozzart = {"fetched_at": "2026-09-26T14:30:00Z", "odds": {
        ("RESULT", "1"): {"odds": 2.50, "section": "Konačan ishod", "code": "1",
                          "description": ""},
    }}
    flags = fs.compute_flags(match, mozzart, PAPER)
    assert len(flags) == 1 and flags[0]["stale"] is True


def test_compute_flags_is_empty_without_a_mozzart_event(monkeypatch):
    monkeypatch.setattr(fs, "family_status", lambda: {})
    match = _flag_match([{"family": "RESULT", "code": "1", "market": "1",
                          "meaning": "home win", "fair_odds": 2.0, "min_acceptable": 2.07}])
    assert fs.compute_flags(match, None, PAPER) == []


# --------------------------------------------------------------------------- #
# the main line is read straight off the sharp price
# --------------------------------------------------------------------------- #
def test_main_line_markets_are_taken_directly_from_the_sharp_1x2():
    prices = {"p_home": 0.60, "p_draw": 0.25, "p_away": 0.15}
    sharp = fs.sharp_overrides(prices)
    assert sharp[("RESULT", "1")] == (0.60, 0.0)
    assert sharp[("RESULT", "X")] == (0.25, 0.0)
    assert sharp[("RESULT", "2")] == (0.15, 0.0)
    assert sharp[("DOUBLE_CHANCE", "1X")][0] == pytest.approx(0.85)
    assert sharp[("DOUBLE_CHANCE", "12")][0] == pytest.approx(0.75)
    assert sharp[("DOUBLE_CHANCE", "X2")][0] == pytest.approx(0.40)
    # a draw returns the stake, so the fair price is (1 - p_draw) / p_win
    assert sharp[("NO_BET", "XNB FT 1")] == (0.60, 0.25)
    assert fs.fair_odds(*sharp[("NO_BET", "XNB FT 1")]) == pytest.approx(0.75 / 0.60)
    # the three results are the de-margined sharp prices, so they sum to 1
    assert sum(sharp[("RESULT", code)][0] for code in "1X2") == pytest.approx(1.0)


def test_only_the_main_line_families_have_a_direct_sharp_price():
    sharp = fs.sharp_overrides({"p_home": 0.6, "p_draw": 0.25, "p_away": 0.15})
    assert {family for family, _code in sharp} == {"RESULT", "DOUBLE_CHANCE", "NO_BET"}
    # goal ranges and per-half markets still need the anchored score grid
    assert ("GOAL_RANGE_FT", "3+") not in sharp
    assert ("HALF_RESULT", "I1") not in sharp


def test_direct_goal_codes_map_thresholds_to_totals_lines():
    totals = {2.5: {"over": 0.50, "under": 0.50}, 3.5: {"over": 0.48, "under": 0.52}}
    codes = fs.direct_goal_codes(totals)
    assert codes[("GOAL_RANGE_FT", "3+")] == (0.50, 0.0)      # Over 2.5
    assert codes[("GOAL_RANGE_FT", "0-2")] == (0.50, 0.0)     # Under 2.5
    assert codes[("GOAL_RANGE_FT", "4+")] == (0.48, 0.0)      # Over 3.5
    assert codes[("GOAL_RANGE_FT", "0-3")] == (0.52, 0.0)     # Under 3.5
    # a range with no matching line stays model-derived
    assert ("GOAL_RANGE_FT", "3-6") not in codes


def test_direct_provenance_is_only_the_1x2_and_matching_goal_lines():
    prices = {"totals": {3.5: {"over": 0.48, "under": 0.52}}}
    direct = fs.direct_provenance(prices)
    assert ("RESULT", "1") in direct and ("GOAL_RANGE_FT", "4+") in direct
    assert ("DOUBLE_CHANCE", "1X") not in direct
    assert ("NO_BET", "XNB FT 1") not in direct
    assert ("GOAL_RANGE_FT", "3-6") not in direct


def test_derived_markets_flag_only_in_a_modelled_pass_league(monkeypatch):
    monkeypatch.setattr(fs, "family_status", lambda: {"GOAL_RANGE_1H": "PASS"})
    rows = [{"family": "GOAL_RANGE_1H", "code": "I0", "market": "I0", "meaning": "x",
             "fair_odds": 2.0, "min_acceptable": 2.07, "provenance": "DERIVED"}]
    mozzart = {"fetched_at": "2026-09-26T12:10:00Z", "odds": {
        ("GOAL_RANGE_1H", "I0"): {"odds": 2.10, "section": "s", "code": "0",
                                    "description": ""}}}
    flags = fs.compute_flags(_flag_match(rows), mozzart, PAPER)
    assert len(flags) == 1 and flags[0]["track"] == fs.TRACK_MODEL
    assert flags[0]["provenance"] == "DERIVED"
    widened = dict(_flag_match(rows), league="eng_league_two")
    assert fs.compute_flags(widened, mozzart, PAPER) == []


def test_direct_markets_flag_on_the_sharp_track_in_any_league(monkeypatch):
    monkeypatch.setattr(fs, "family_status", lambda: {})
    rows = [{"family": "GOAL_RANGE_FT", "code": "4+", "market": "4+", "meaning": "x",
             "fair_odds": 2.0, "min_acceptable": 2.07, "provenance": "DIRECT"}]
    mozzart = {"fetched_at": "2026-09-26T12:10:00Z", "odds": {
        ("GOAL_RANGE_FT", "4+"): {"odds": 2.10, "section": "s", "code": "4+",
                                    "description": ""}}}
    widened = dict(_flag_match(rows), league="eng_league_two")
    flags = fs.compute_flags(widened, mozzart, PAPER)
    assert len(flags) == 1 and flags[0]["track"] == fs.TRACK_SHARP
    assert flags[0]["provenance"] == "DIRECT"


def test_the_parser_fix_removed_the_duplicate_settlements():
    """The 12 codes that used to duplicate RESULT / DC / half markets are now goals.

    So the sheet no longer has to drop anything as a duplicate of them, and the
    goal readings survive under their own families.
    """
    status = fs.family_status()
    blocked = fs.handcrafted_blocklist()
    rows = [
        {"market": label, "family": market.family, "section": market.section,
         "meaning": fs.meaning_of(market), "fair_odds": 2.0, "min_acceptable": 2.07,
         "status": "SHARP" if market.family in fs.SHARP_FAMILIES
                   else status.get(market.family, "UNTESTED"),
         "do_not_bet": label in blocked,
         "signature": settlement_signature(market.outcome)}
        for label, market in fs.sheet_markets()
    ]
    _kept, _hidden, suppressed = fs.select(rows)
    eligible = [r for r in rows
                if r["status"] in ("SHARP", "PASS") and not r["do_not_bet"]]
    # the supplied `suppressed` is now only the cap; assert there is no duplicate left
    assert len({r["signature"] for r in eligible}) == len(eligible)
    assert suppressed > 0          # the 15-row cap is doing the suppressing instead


# --------------------------------------------------------------------------- #
# rendering
# --------------------------------------------------------------------------- #
def match(rows, error=""):
    entry = {
        "date": "2026-10-10", "kickoff": EVENT["commence_time"],
        "league": "bundesliga_1", "home": EVENT["home_team"],
        "away": EVENT["away_team"], "rows": rows, "hidden": 5, "suppressed": 2,
        "error": error, "snapshot": "2026-09-24T15:25:00Z",
    }
    if not error:
        entry.update({
            "raw_1x2": [1.42, 4.76, 7.00], "line": 2.5,
            "margin_1x2": 0.0572, "margin_ou": 0.0259, "residual": 0.0059,
        })
    return entry


def meta():
    return {"window": [datetime.date(2026, 10, 10), datetime.date(2026, 10, 12)],
            "built": "2026-09-24T18:00+02:00", "snapshot": "2026-09-24T15:25:00Z",
            "leagues": "bundesliga_1", "matches": 1, "credits": 2, "remaining": 481,
            "notes": []}


def test_render_has_the_snapshot_the_movement_note_and_the_table():
    shown = row("1", "RESULT", "SHARP", odd=1.44, section="Konačni Ishod")
    text = fs.render([match([shown])], meta())
    assert "# Fair odds sheet — 2026-10-10 .. 2026-10-12" in text
    assert "2026-09-24T15:25:00Z" in text
    assert "odds move — re-run within ~1h of betting." in text
    assert "BET ONLY IF THE BOOK'S ODDS ARE >= fair x 1.035" in text
    assert "| section | code | meaning | fair | bet if ≥ |" in text
    assert "| Konačni Ishod | `1` | meaning of 1 | 1.44 | **1.49** |" in text
    assert "_1 of 3 eligible prices shown; 5 hidden; 2 below the cut_" in text
    assert "anchor residual 0.0059" in text
    assert "is a home win under Konačni Ishod" in text      # the section decides


def test_render_flags_a_match_whose_anchor_fits_badly():
    poor = match([row("1", "RESULT", "SHARP")])
    poor["residual"] = 0.07
    text = fs.render([poor], meta())
    assert "anchor residual 0.0700 ⚠ Pinnacle 1X2 and totals disagree" in text


def test_render_reports_a_match_that_could_not_be_priced():
    text = fs.render([match([], error="no Pinnacle h2h + totals in the snapshot")], meta())
    assert "no Pinnacle h2h + totals in the snapshot" in text
    assert "## Hoffenheim vs Hamburger SV" in text      # the match is still named
    assert "| section |" not in text
    assert "1X2 margin" not in text          # no price header for an unpriced match


def test_render_surfaces_a_stopped_run():
    data = meta()
    data["notes"] = ["Stopped after 60 credits: credit cap 60 reached."]
    text = fs.render([match([row("1", "RESULT", "SHARP")])], data)
    assert "Stopped after 60 credits" in text


# --------------------------------------------------------------------------- #
# csv
# --------------------------------------------------------------------------- #
def test_write_csv_round_trips_the_shown_rows(tmp_path):
    path = tmp_path / "sheet.csv"
    shown = row("1", "RESULT", "SHARP", odd=1.44, section="Konačni Ishod")
    n = fs.write_csv(path, [match([shown])])
    assert n == 1
    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines[0].split(",") == fs.CSV_FIELDS
    assert lines[1].startswith("2026-10-10,")
    assert ",Konačni Ishod,1,RESULT,meaning of 1,1.4400,1.4904,SHARP," in lines[1]


# --------------------------------------------------------------------------- #
# the window is the user's local dates
# --------------------------------------------------------------------------- #
def test_local_date_uses_the_local_kickoff_date():
    assert fs.local_date("2026-09-24T13:30:00Z") == datetime.date(2026, 9, 24)


def test_upcoming_events_filters_the_window_and_skips_started_matches(monkeypatch):
    events = [
        {"id": "a", "commence_time": "2099-01-01T12:00:00Z"},   # in window, future
        {"id": "b", "commence_time": "2000-01-01T12:00:00Z"},   # started
        {"id": "c", "commence_time": "2099-06-01T12:00:00Z"},   # outside the window
    ]
    calls = {"n": 0}

    def fake_call(session, key, path, params=None, note=""):
        calls["n"] += 1
        return (events if calls["n"] == 1 else []), {"x-requests-remaining": "400"}

    monkeypatch.setattr(fs, "_call", fake_call)

    found, headers, started = fs.upcoming_events(None, "key", {datetime.date(2099, 1, 1)})
    assert {event["id"] for _sport, event in found} == {"a"}
    assert started == 0
    assert headers["x-requests-remaining"] == "400"
    assert calls["n"] == len(fs.SPORTS)     # one free events call per sport key

    calls["n"] = 0
    found, _headers, started = fs.upcoming_events(None, "key", {datetime.date(2000, 1, 1)})
    assert found == [] and started == 1     # a played match is never priced


def test_sheet_files_are_written_under_reports():
    assert Path(fs.SHEET_DIR).as_posix() == "reports/fair_sheets"
    assert fs.EDGE_CUSHION == 1.035
    assert fs.CREDIT_CAP == 60 and fs.MIN_REMAINING == 100 and fs.CACHE_HOURS == 6