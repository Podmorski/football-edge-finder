"""Local log of every The Odds API request.

Mirrors ``api_log.py`` for API-Football. Stored at
``logs/odds_api_requests.csv`` (gitignored). Credits are tracked from the
``x-requests-used`` / ``x-requests-remaining`` / ``x-requests-last`` response
headers, which are authoritative.
"""

from __future__ import annotations

import csv
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

LOG_DIR = Path("logs")
LOG_PATH = LOG_DIR / "odds_api_requests.csv"
FIELDS = [
    "timestamp",
    "endpoint",
    "params",
    "http_status",
    "cost",
    "used",
    "remaining",
    "notes",
]


def _ensure_log() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    if not LOG_PATH.exists():
        with LOG_PATH.open("w", newline="", encoding="utf-8") as fh:
            csv.DictWriter(fh, fieldnames=FIELDS).writeheader()


def log_request(
    endpoint: str,
    params: Any,
    http_status: Any,
    cost: Any = "",
    used: Any = "",
    remaining: Any = "",
    notes: str = "",
) -> None:
    _ensure_log()
    with LOG_PATH.open("a", newline="", encoding="utf-8") as fh:
        csv.DictWriter(fh, fieldnames=FIELDS).writerow(
            {
                "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "endpoint": endpoint,
                "params": str(params),
                "http_status": str(http_status),
                "cost": str(cost),
                "used": str(used),
                "remaining": str(remaining),
                "notes": notes,
            }
        )


def read_rows() -> list[dict[str, str]]:
    if not LOG_PATH.exists():
        return []
    with LOG_PATH.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def credits_used_today() -> int:
    key = date.today().isoformat()
    total = 0
    for row in read_rows():
        if row["timestamp"][:10] != key:
            continue
        try:
            total += int(float(row["cost"]))
        except (TypeError, ValueError):
            continue
    return total


def credits_used_this_month() -> int:
    key = date.today().strftime("%Y-%m")
    total = 0
    for row in read_rows():
        if row["timestamp"][:7] != key:
            continue
        try:
            total += int(float(row["cost"]))
        except (TypeError, ValueError):
            continue
    return total


def print_today() -> None:
    today = date.today()
    rows = [r for r in read_rows() if r["timestamp"][:10] == today.isoformat()]
    print(f"The Odds API calls logged for {today}: {len(rows)} "
          f"(credits {credits_used_today()})")
    for row in rows:
        print(f"  {row['timestamp']} | {row['endpoint']} | {row['params'][:60]} | "
              f"HTTP {row['http_status']} | cost {row['cost']} | "
              f"used {row['used']} | remaining {row['remaining']} | {row['notes'][:60]}")


if __name__ == "__main__":
    print_today()
    sys.exit(0)