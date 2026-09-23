"""Tests that the ledger is genuinely append-only.

Hermetic: every test uses a temporary ledger path.
"""

from __future__ import annotations

import pytest

from core import ledger


def test_appending_never_rewrites_existing_bytes(tmp_path):
    path = tmp_path / "ledger.csv"
    ledger.log_evaluation(path=path, league="L", market="1X2", notes="first")
    snapshot = path.read_bytes()

    ledger.log_evaluation(path=path, league="L", market="1X2", notes="second")
    grown = path.read_bytes()

    assert grown.startswith(snapshot), "earlier bytes were rewritten"
    assert len(grown) > len(snapshot)
    assert len(ledger.read_ledger(path)) == 2


def test_supersede_marks_and_keeps_the_original(tmp_path):
    path = tmp_path / "ledger.csv"
    original = ledger.log_evaluation(path=path, league="L", market="1X2", notes="v1")
    snapshot = path.read_bytes()

    replacement = ledger.log_evaluation(path=path, league="L", market="1X2", notes="v2")
    ledger.supersede(original["run_id"], replacement["run_id"], "recomputed", path=path)

    # Original bytes still present, file only grew.
    raw = path.read_bytes()
    assert raw.startswith(snapshot)
    rows = ledger.read_ledger(path)
    assert len(rows) == 3, "supersession must not delete the original row"

    active_ids = {row["run_id"] for row in ledger.active_rows(path)}
    assert original["run_id"] not in active_ids, "superseded row should be inactive"
    assert replacement["run_id"] in active_ids
    assert f"{ledger.SUPERSEDE_PREFIX}{original['run_id']}" not in active_ids


def test_marker_rows_do_not_collide_with_evaluation_ids(tmp_path):
    path = tmp_path / "ledger.csv"
    row = ledger.log_evaluation(path=path, league="L")
    ledger.supersede(row["run_id"], "other", "reason", path=path)
    marker = ledger.read_ledger(path)[-1]
    assert marker["run_id"] == f"{ledger.SUPERSEDE_PREFIX}{row['run_id']}"
    assert marker["superseded_by"] == "other"


def test_append_note_is_append_only(tmp_path):
    path = tmp_path / "ledger.csv"
    ledger.log_evaluation(path=path, league="L")
    snapshot = path.read_bytes()

    ledger.append_note("something happened", path=path)
    assert path.read_bytes().startswith(snapshot)
    assert ledger.read_ledger(path)[-1]["notes"] == "something happened"


def test_unknown_fields_are_rejected(tmp_path):
    path = tmp_path / "ledger.csv"
    with pytest.raises(KeyError):
        ledger.log_evaluation(path=path, not_a_field=1)


def test_read_refuses_a_legacy_header(tmp_path):
    path = tmp_path / "ledger.csv"
    path.write_text("league,market\nL,1X2\n", encoding="utf-8")
    with pytest.raises(ledger.LedgerSchemaError):
        ledger.read_ledger(path)


def test_migration_is_idempotent_and_preserves_rows(tmp_path):
    path = tmp_path / "ledger.csv"
    path.write_text("timestamp,league,market\n2020-01-01,L,1X2\n", encoding="utf-8")

    assert ledger.migrate_legacy(path) is True
    assert ledger.migrate_legacy(path) is False  # second call is a no-op

    rows = ledger.read_ledger(path)
    evaluations = [r for r in rows if not str(r["run_id"]).startswith(ledger.NOTE_PREFIX)]
    assert len(evaluations) == 1
    assert evaluations[0]["league"] == "L"
    assert evaluations[0]["run_id"]