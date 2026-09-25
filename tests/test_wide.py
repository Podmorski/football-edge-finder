"""Widening: league registry, tracks, flag audit, scores and the scheduler XML."""

from __future__ import annotations

from datetime import date

import fair_sheet as fs
import flag_audit
import paper_trade
import scheduler
import scores
from core import league_registry


# --------------------------------------------------------------------------- #
# registry
# --------------------------------------------------------------------------- #
def test_tracks_and_modelled_league_membership():
    modelled = league_registry.slug_of(modelled=True)
    assert set(modelled) == {"bundesliga_1", "bundesliga_2", "league_one_t3", "ligue_2_t2"}
    wide = league_registry.slug_of(track=league_registry.SHARP_WIDE)
    assert wide and all(league_registry.track_of(slug) == "SHARP_WIDE" for slug in wide)
    assert not (set(wide) & set(modelled))
    assert league_registry.is_modelled("bundesliga_1")
    assert not league_registry.is_modelled("eng_premier")


def test_a_pending_mozzart_league_is_inactive_until_its_resume_date():
    before = league_registry.pending_topups(date(2026, 9, 24))
    assert before == []                      # 2. Bundesliga / Ligue 2 resume after 2026-10-08
    after = dict(league_registry.pending_topups(date(2026, 10, 9)))
    assert after.get("bundesliga_2") == "Nemačka 2"
    assert after.get("ligue_2_t2") == "Francuska 2"
    assert not league_registry.is_active("bundesliga_2")   # no Mozzart listing yet


def test_odds_api_keys_cover_the_active_leagues():
    for slug in league_registry.slug_of():
        assert league_registry.odds_api_key(slug)
    key = league_registry.odds_api_key("eng_premier")
    assert key is not None and fs.SPORTS[key] == "eng_premier"


# --------------------------------------------------------------------------- #
# tracks in the flags
# --------------------------------------------------------------------------- #
def _match(slug, rows):
    return {"home": "A", "away": "B", "league": slug,
            "kickoff": "2099-01-01T13:00:00Z", "snapshot": "2099-01-01T12:00:00Z",
            "rows": rows}


PAPER = {"edge_cushion": 1.035, "ev_haircut": 0.20, "max_gap_minutes": 60}


def _rows():
    return [
        {"family": "RESULT", "code": "1", "market": "1", "meaning": "home win",
         "fair_odds": 2.0, "min_acceptable": 2.07, "provenance": "DIRECT"},
        {"family": "HALF_RESULT", "code": "I1", "market": "I1", "meaning": "1H home win",
         "fair_odds": 2.0, "min_acceptable": 2.07, "provenance": "DERIVED"},
    ]


def _mozzart():
    return {"fetched_at": "2099-01-01T12:05:00Z", "odds": {
        ("RESULT", "1"): {"odds": 2.20, "section": "Konačan ishod", "code": "1",
                          "description": ""},
        ("HALF_RESULT", "I1"): {"odds": 2.20, "section": "Prvo poluvreme", "code": "1",
                                "description": ""},
    }}


def test_model_families_are_limited_to_the_four(monkeypatch):
    monkeypatch.setattr(fs, "family_status", lambda: {"HALF_RESULT": "PASS"})
    widened = fs.compute_flags(_match("eng_premier", _rows()), _mozzart(), PAPER)
    assert [f["family"] for f in widened] == ["RESULT"]        # HALF_RESULT is not allowed
    assert widened[0]["track"] == "SHARP_WIDE"

    modelled = fs.compute_flags(_match("league_one_t3", _rows()), _mozzart(), PAPER)
    tracks = {f["family"]: f["track"] for f in modelled}
    assert tracks == {"RESULT": "SHARP_WIDE", "HALF_RESULT": "MODEL_4L"}


# --------------------------------------------------------------------------- #
# paper ledger carries the track
# --------------------------------------------------------------------------- #
def test_paper_ledger_records_and_reports_the_track(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(paper_trade, "LOG", tmp_path / "paper_bets.csv")
    flag = {
        "kickoff": "2099-01-01T13:00:00Z", "league": "eng_premier", "track": "SHARP_WIDE",
        "home": "A", "away": "B", "family": "RESULT", "section": "Konačan ishod",
        "code": "1", "meaning": "home win", "mozzart_odds": 2.10, "fair_odds": 2.00,
        "min_acceptable": 2.07, "ev": 0.05, "stale": False,
        "mozzart_snapshot": "2099-01-01T12:09:00Z", "pinnacle_snapshot": "2099-01-01T12:00:00Z",
    }
    assert paper_trade.record([flag]) == 1
    assert paper_trade.read_rows()[0]["track"] == "SHARP_WIDE"
    paper_trade.report()
    assert "by track" in capsys.readouterr().out


# --------------------------------------------------------------------------- #
# flag audit
# --------------------------------------------------------------------------- #
def _flag(track, family="RESULT"):
    return {"home": "A", "away": "B", "kickoff": "2099-01-01T13:00:00Z", "family": family,
            "track": track, "section": "Konačan ishod", "code": "1", "meaning": "home win",
            "mozzart_odds": 2.10, "fair_odds": 2.00, "min_acceptable": 2.07,
            "mozzart_snapshot": "2099-01-01T12:09:00Z",
            "pinnacle_snapshot": "2099-01-01T12:00:00Z"}


def test_flag_audit_keeps_ten_per_track_and_marks_a_suspect_rate(tmp_path, monkeypatch):
    monkeypatch.setattr(flag_audit, "STATE", tmp_path / "state.json")
    report = tmp_path / "flag_audit.md"
    flags = [_flag("SHARP_WIDE") for _ in range(12)]
    kept = flag_audit.audit(flags, matches=100, report=report)
    assert kept == flag_audit.SAMPLE_PER_TRACK          # only the first 10 kept
    text = report.read_text(encoding="utf-8")
    assert "## SHARP_WIDE — **SUSPECT**" in text         # 12/100 = 12% > 3 x 3.33%
    assert "Konačan ishod" in text and "2.100" in text   # raw price + section are dumped

    monkeypatch.setattr(flag_audit, "STATE", tmp_path / "state2.json")
    ok = tmp_path / "ok.md"
    flag_audit.audit([_flag("MODEL_4L")], matches=100, report=ok)
    assert "## MODEL_4L — ok" in ok.read_text(encoding="utf-8")   # 1/100 is well under


# --------------------------------------------------------------------------- #
# scores fallback
# --------------------------------------------------------------------------- #
def test_scores_find_result_matches_a_finished_event(monkeypatch):
    canned = [{"completed": True, "home_team": "Arsenal", "away_team": "Chelsea",
               "scores": [{"name": "Arsenal", "score": "2"}, {"name": "Chelsea", "score": "1"}]}]
    monkeypatch.setattr(scores, "_call_scores", lambda *a, **k: (canned, 2))
    row = scores.find_result("eng_premier", date(2026, 9, 20), "Arsenal", "Chelsea",
                             session=object(), key="k")
    assert row is not None and row.fthg == 2 and row.ftag == 1
    # an unplayed event is ignored
    monkeypatch.setattr(scores, "_call_scores",
                        lambda *a, **k: ([{"completed": False, "home_team": "Arsenal",
                                           "away_team": "Chelsea", "scores": []}], 2))
    assert scores.find_result("eng_premier", date(2026, 9, 20), "Arsenal", "Chelsea",
                              session=object(), key="k") is None


# --------------------------------------------------------------------------- #
# scheduler XML
# --------------------------------------------------------------------------- #
def test_scheduler_registers_five_resilient_tasks():
    tasks = scheduler.tasks()
    assert {t["name"] for t in tasks} == {
        "FairSheetDaily", "FairSheetPreKick", "PaperClose", "ResultsDaily", "Weekly"}
    for task in tasks:
        xml = task["xml"]
        assert "<StartWhenAvailable>true</StartWhenAvailable>" in xml   # missed start
        assert "<WakeToRun>true</WakeToRun>" in xml                     # wake from sleep
        assert "<WorkingDirectory>" in xml                              # run.py needs the root
        assert "scheduler.log" in xml                                   # every run is logged
        assert "&amp;" in xml                                            # the 2>&1 redirect is escaped


def test_scheduler_dry_run_lists_every_task(capsys):
    assert scheduler.dry_run() == 0
    out = capsys.readouterr().out
    for name in ("FairSheetDaily", "PaperClose", "ResultsDaily", "Weekly"):
        assert name in out