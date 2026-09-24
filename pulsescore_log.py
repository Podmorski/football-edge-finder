"""Local log of every PulseScore (Mozzart feed) request.

Stored at ``logs/pulsescore_requests.csv`` (gitignored). The provider's own
counter is not exposed on the free tier, so this log is the **source of truth**
for quota usage, exactly as ``api_log.py`` is for API-Football.

Budget (config): a **monthly cap of 400** requests and a **stop threshold of 50**
remaining. A run refuses to start a call when the month's usage has reached the
cap or when fewer than 50 requests are left in the month.
"""

from __future__ import annotations

import csv
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

LOG_DIR = Path("logs")
LOG_PATH = LOG_DIR / "pulsescore_requests.csv"
FIELDS = [
    "timestamp",
    "endpoint",
    "params",
    "http_status",
    "cost",
    "used_month",
    "remaining_month",
    "notes",
]

MONTHLY_CAP = 400
STOP_REMAINING = 50


def _ensure_log() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    if not LOG_PATH.exists():
        with LOG_PATH.open("w", newline="", encoding="utf-8") as fh:
            csv.DictWriter(fh, fieldnames=FIELDS).writeheader()


def log_request(
    endpoint: str,
    params: Any,
    http_status: Any,
    cost: Any = 1,
    notes: str = "",
) -> None:
    """Append one request row, filling the month's running totals."""
    _ensure_log()
    used = used_this_month() + (int(float(cost)) if str(cost) else 0)
    with LOG_PATH.open("a", newline="", encoding="utf-8") as fh:
        csv.DictWriter(fh, fieldnames=FIELDS).writerow(
            {
                "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "endpoint": endpoint,
                "params": str(params),
                "http_status": str(http_status),
                "cost": str(cost),
                "used_month": str(used),
                "remaining_month": str(max(MONTHLY_CAP - used, 0)),
                "notes": notes,
            }
        )


def read_rows() -> list[dict[str, str]]:
    if not LOG_PATH.exists():
        return []
    with LOG_PATH.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _month_key() -> str:
    return date.today().strftime("%Y-%m")


def used_this_month() -> int:
    key = _month_key()
    total = 0
    for row in read_rows():
        if row["timestamp"][:7] != key:
            continue
        try:
            total += int(float(row["cost"]))
        except (TypeError, ValueError):
            continue
    return total


def remaining_this_month() -> int:
    return max(MONTHLY_CAP - used_this_month(), 0)


def budget_ok() -> tuple[bool, str]:
    """(allowed, reason). Refuses when the cap is hit or the reserve is reached."""
    used = used_this_month()
    if used >= MONTHLY_CAP:
        return False, f"monthly cap {MONTHLY_CAP} reached ({used} used)"
    if remaining_this_month() < STOP_REMAINING:
        return False, (f"only {remaining_this_month()} requests left this month "
                       f"(stop threshold {STOP_REMAINING})")
    return True, ""


def print_month() -> None:
    print(f"PulseScore requests this month ({_month_key()}): {used_this_month()} "
          f"of {MONTHLY_CAP} (remaining {remaining_this_month()})")
    for row in read_rows():
        if row["timestamp"][:7] == _month_key():
            print(f"  {row['timestamp']} | {row['endpoint']} | {row['params'][:60]} | "
                  f"HTTP {row['http_status']} | {row['notes'][:60]}")


if __name__ == "__main__":
    print_month()
    sys.exit(0)