"""The evaluation ledger — append-only.

Every evaluation is recorded here, **including failures**. A negative result is
information, not something to hide.

Invariants
----------
* Rows are **never deleted and never rewritten**. ``log_evaluation``,
  ``append_note`` and ``supersede`` only ever append.
* A superseded row stays in the file; it is superseded by an appended *marker*
  row whose ``run_id`` is ``supersede:<original run_id>`` and whose
  ``superseded_by`` names the replacement run. Use :func:`active_rows` to read
  the ledger ignoring superseded rows.

Columns
-------
``run_id``         unique id for the row (``note:``/``supersede:`` prefixed for
                   marker rows, so they can never collide with evaluations).
``superseded_by``  on a marker row: the ``run_id`` that replaces the row named
                   in the marker's own ``run_id``.
"""

from __future__ import annotations

import csv
import uuid
from datetime import datetime, timezone
from pathlib import Path

from core.splits import git_hash

LEDGER_PATH = Path("research/ledger.csv")

FIELDS = [
    "run_id",
    "timestamp",
    "git_hash",
    "league",
    "market",
    "selection",
    "rule_config",
    "split",
    "n_predictions",
    "log_loss",
    "brier",
    "benchmark_name",
    "benchmark_log_loss",
    "n_bets",
    "roi",
    "mean_clv",
    "superseded_by",
    "notes",
]

NOTE_PREFIX = "note:"
SUPERSEDE_PREFIX = "supersede:"


class LedgerSchemaError(RuntimeError):
    """Raised when research/ledger.csv predates the append-only schema."""


def _path(path: Path | None = None) -> Path:
    return Path(path) if path else LEDGER_PATH


def new_run_id() -> str:
    return uuid.uuid4().hex[:12]


def _read_header(path: Path) -> list[str] | None:
    if not path.exists():
        return None
    with path.open(newline="", encoding="utf-8") as fh:
        return next(csv.reader(fh), None)


def _append(row: dict[str, object], path: Path | None = None) -> dict[str, object]:
    """Append one row. Never modifies existing content."""
    target = _path(path)
    header = _read_header(target)
    if header is None:
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("w", newline="", encoding="utf-8") as fh:
            csv.DictWriter(fh, fieldnames=FIELDS).writeheader()
    elif header != FIELDS:
        raise LedgerSchemaError(
            f"{target} has header {header}, expected {FIELDS}. "
            "Run core.ledger.migrate_legacy() to upgrade it."
        )

    with target.open("a", newline="", encoding="utf-8") as fh:
        csv.DictWriter(fh, fieldnames=FIELDS).writerow(row)
    return row


def log_evaluation(path: Path | None = None, **kwargs: object) -> dict[str, object]:
    """Append one evaluation row. Unknown keys are rejected."""
    unknown = set(kwargs) - set(FIELDS)
    if unknown:
        raise KeyError(f"Unknown ledger field(s): {sorted(unknown)}")

    row: dict[str, object] = {field: "" for field in FIELDS}
    row.update(kwargs)
    row["run_id"] = row.get("run_id") or new_run_id()
    row["timestamp"] = row.get("timestamp") or datetime.now(timezone.utc).isoformat(
        timespec="seconds"
    )
    row["git_hash"] = row.get("git_hash") or git_hash()
    return _append(row, path)


def append_note(note: str, path: Path | None = None) -> dict[str, object]:
    """Append a free-text note row (e.g. to record a process event)."""
    row: dict[str, object] = {field: "" for field in FIELDS}
    row["run_id"] = f"{NOTE_PREFIX}{new_run_id()}"
    row["timestamp"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    row["git_hash"] = git_hash()
    row["notes"] = note
    return _append(row, path)


def supersede(
    run_id: str, superseded_by: str, reason: str, path: Path | None = None
) -> dict[str, object]:
    """Mark ``run_id`` as superseded, by appending a marker row.

    The original row is left untouched.
    """
    row: dict[str, object] = {field: "" for field in FIELDS}
    row["run_id"] = f"{SUPERSEDE_PREFIX}{run_id}"
    row["timestamp"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    row["git_hash"] = git_hash()
    row["superseded_by"] = superseded_by
    row["notes"] = f"SUPERSESSION: replaces run_id={run_id}; {reason}"
    return _append(row, path)


def read_ledger(path: Path | None = None) -> list[dict[str, str]]:
    target = _path(path)
    if not target.exists():
        return []
    header = _read_header(target)
    if header != FIELDS:
        raise LedgerSchemaError(
            f"{target} has header {header}, expected {FIELDS}. "
            "Run core.ledger.migrate_legacy() to upgrade it."
        )
    with target.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def superseded_ids(rows: list[dict[str, str]] | None = None) -> set[str]:
    rows = rows if rows is not None else read_ledger()
    return {
        row["run_id"][len(SUPERSEDE_PREFIX) :]
        for row in rows
        if str(row["run_id"]).startswith(SUPERSEDE_PREFIX)
    }


def active_rows(path: Path | None = None) -> list[dict[str, str]]:
    """Rows that are neither supersession markers nor superseded."""
    rows = read_ledger(path)
    dead = superseded_ids(rows)
    return [
        row
        for row in rows
        if not str(row["run_id"]).startswith(SUPERSEDE_PREFIX)
        and row["run_id"] not in dead
    ]


def migrate_legacy(path: Path | None = None) -> bool:
    """One-off upgrade of a pre-``run_id`` ledger. Idempotent.

    This is the only operation that rewrites existing bytes; it is recorded as a
    note row so the change is visible in the ledger itself.
    """
    target = _path(path)
    if not target.exists():
        return False
    header = _read_header(target)
    if header == FIELDS:
        return False
    if header is None:
        return False

    with target.open(newline="", encoding="utf-8") as fh:
        old_rows = list(csv.DictReader(fh))

    migrated = []
    for old in old_rows:
        row: dict[str, object] = {field: "" for field in FIELDS}
        for key, value in old.items():
            if key in FIELDS and key not in ("run_id", "superseded_by"):
                row[key] = value
        row["run_id"] = row.get("run_id") or new_run_id()
        migrated.append(row)

    legacy_count = len(old_rows)
    with target.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(migrated)

    append_note(
        f"SCHEMA MIGRATION: upgraded ledger to append-only schema; "
        f"{legacy_count} legacy row(s) received generated run_id values. "
        "No evaluation data was altered.",
        path=target,
    )
    return True