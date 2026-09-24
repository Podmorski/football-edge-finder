"""Daily health report — ``reports/health.md``.

PART D2. Once a day (the 08:00 results task) this summarises the loop for a
human: the last run of each scheduled task, recent failures, API usage for both
providers, and today's flags. Everything is read from the local logs and the
paper ledger — no external call is made.
"""

from __future__ import annotations

import csv
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import odds_api_log
import pulsescore_log

ROOT = Path(__file__).resolve().parent
SCHEDULER_LOG = ROOT / "logs" / "scheduler.log"
PAPER_LOG = ROOT / "data" / "paper" / "paper_bets.csv"
OUT = ROOT / "reports" / "health.md"

TASK_MARKERS = {
    "fair-sheet ": "FairSheetDaily",
    "kickoff-run": "FairSheetPreKick",
    "paper-close:": "PaperClose",
    "paper-settle:": "ResultsDaily",
    "weekly:": "Weekly",
}


def _tail(path: Path, limit: int = 40) -> list[str]:
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    return lines[-limit:]


def _last_runs(lines: list[str]) -> dict[str, str]:
    """The most recent matching line per task (logs are append-only)."""
    out: dict[str, str] = {}
    for line in lines:
        for marker, task in TASK_MARKERS.items():
            if marker in line:
                out[task] = line.strip()[:160]
    return out


def _paper_today() -> tuple[int, int]:
    """(bets recorded today, flags per track today)."""
    if not PAPER_LOG.exists():
        return 0, 0
    today = date.today().isoformat()
    count = 0
    with PAPER_LOG.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            if row.get("date") == today:
                count += 1
    return count, count


def _failures(lines: list[str]) -> list[str]:
    bad = []
    for line in lines:
        low = line.lower()
        if any(word in low for word in ("traceback", "error:", "failed", "refused")):
            bad.append(line.strip()[:160])
    return bad[-8:]


def write() -> int:
    lines = _tail(SCHEDULER_LOG)
    last = _last_runs(lines)
    ps_used = pulsescore_log.used_this_month()
    ps_left = pulsescore_log.remaining_this_month()
    odds_used = odds_api_log.credits_used_today()
    odds_rows = odds_api_log.read_rows()
    odds_remaining = odds_rows[-1]["remaining"] if odds_rows else "?"
    bets_today, _ = _paper_today()
    failures = _failures(lines)

    out = [
        "# Health",
        "",
        f"- generated {datetime.now(timezone.utc).isoformat(timespec='seconds')}",
        f"- PulseScore: {ps_used} used this month, {ps_left} remaining "
        f"(cap {pulsescore_log.MONTHLY_CAP})",
        f"- The Odds API: {odds_used} credits today, account remaining {odds_remaining}",
        f"- paper bets recorded today: {bets_today}",
        "",
        "## Last run per task",
        "",
    ]
    if last:
        out += [f"- **{task}**: `{run}`" for task, run in last.items()]
    else:
        out += ["_no scheduled runs in logs/scheduler.log yet._"]
    out += ["", "## Recent failures / warnings", ""]
    out += [f"- `{line}`" for line in failures] or ["- none"]
    out += [
        "",
        "## Disable all tasks",
        "",
        "```",
        "./venv/Scripts/python.exe scheduler.py delete      # remove them",
        "./venv/Scripts/python.exe scheduler.py disable     # keep, stop",
        "```",
        "",
    ]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(out), encoding="utf-8")
    print(f"wrote {OUT} ({len(lines)} scheduler log lines scanned)")
    return 0


if __name__ == "__main__":
    sys.exit(write())