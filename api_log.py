"""Local log of every API-Football request we make.

The provider's own ``/status`` counter lags behind reality, so this log is the
source of truth for quota usage. Stored at ``logs/api_requests.csv`` and
gitignored.

Every API-Football call in this project must go through :func:`log_request`.
"""

from __future__ import annotations

import csv
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

LOG_DIR = Path("logs")
LOG_PATH = LOG_DIR / "api_requests.csv"
FIELDS = ["timestamp", "endpoint", "params", "http_status", "results_count", "errors"]

PRIOR_ESTIMATE_ENDPOINT = "prior-estimate"


def _ensure_log() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    if not LOG_PATH.exists():
        with LOG_PATH.open("w", newline="", encoding="utf-8") as fh:
            csv.DictWriter(fh, fieldnames=FIELDS).writeheader()


def log_request(
    endpoint: str,
    params: Any,
    http_status: Any,
    results_count: Any,
    errors: Any,
    timestamp: str | None = None,
) -> None:
    """Append one request record. Returns ``None``; the log is the side effect."""
    _ensure_log()
    record = {
        "timestamp": timestamp or datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "endpoint": endpoint,
        "params": str(params),
        "http_status": str(http_status),
        "results_count": str(results_count),
        "errors": str(errors),
    }
    with LOG_PATH.open("a", newline="", encoding="utf-8") as fh:
        csv.DictWriter(fh, fieldnames=FIELDS).writerow(record)


def read_rows() -> list[dict[str, str]]:
    if not LOG_PATH.exists():
        return []
    with LOG_PATH.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def rows_for_day(day: date) -> list[dict[str, str]]:
    key = day.isoformat()
    return [r for r in read_rows() if r["timestamp"][:10] == key]


def count_for_day(day: date) -> int:
    """Count logged requests for a day, honouring summary rows' own count."""
    total = 0
    for row in rows_for_day(day):
        if row["endpoint"] == PRIOR_ESTIMATE_ENDPOINT:
            try:
                total += int(float(row["results_count"]))
            except (TypeError, ValueError):
                total += 1
        else:
            total += 1
    return total


def today_count() -> int:
    return count_for_day(date.today())


def log_prior_estimate(count: int, day: str, note: str) -> bool:
    """Log one summary row for calls made before logging existed.

    Idempotent: does nothing if a prior-estimate row already exists.
    Returns True if a row was written.
    """
    if any(r["endpoint"] == PRIOR_ESTIMATE_ENDPOINT for r in read_rows()):
        return False
    log_request(
        endpoint=PRIOR_ESTIMATE_ENDPOINT,
        params=note,
        http_status="",
        results_count=count,
        errors="provider /status lagged (reported 9)",
        timestamp=f"{day}T00:00:00+00:00",
    )
    return True


def print_today() -> None:
    today = date.today()
    rows = rows_for_day(today)
    print(f"API-Football requests logged for {today}: {count_for_day(today)}")
    if not rows:
        print("  (no rows)")
        return
    print(f"  {'timestamp':<25} {'endpoint':<28} {'status':<6} {'results':<8} params")
    for row in rows:
        print(
            f"  {row['timestamp']:<25} {row['endpoint']:<28} {row['http_status']:<6} "
            f"{row['results_count']:<8} {row['params'][:60]}"
        )
        if row["errors"] and row["errors"] != "[]":
            print(f"    errors: {row['errors'][:100]}")


if __name__ == "__main__":
    print_today()
    sys.exit(0)