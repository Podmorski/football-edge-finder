"""The evaluation ledger.

Every evaluation is recorded here — **including failures**. A negative result is
information, not something to hide.

One row per evaluation, appended by ``log_evaluation``.
"""

from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path

from core.splits import git_hash

LEDGER_PATH = Path("research/ledger.csv")

FIELDS = [
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
    "notes",
]


def log_evaluation(**kwargs: object) -> dict[str, object]:
    """Append one evaluation row. Unknown keys are rejected."""
    unknown = set(kwargs) - set(FIELDS)
    if unknown:
        raise KeyError(f"Unknown ledger field(s): {sorted(unknown)}")

    row: dict[str, object] = {field: "" for field in FIELDS}
    row.update(kwargs)
    row["timestamp"] = row.get("timestamp") or datetime.now(timezone.utc).isoformat(
        timespec="seconds"
    )
    row["git_hash"] = row.get("git_hash") or git_hash()

    LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
    is_new = not LEDGER_PATH.exists()
    with LEDGER_PATH.open("a", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDS)
        if is_new:
            writer.writeheader()
        writer.writerow(row)
    return row


def read_ledger() -> list[dict[str, str]]:
    if not LEDGER_PATH.exists():
        return []
    with LEDGER_PATH.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))