"""One hard-capped guard in front of every PulseScore / The Odds API call.

Both feeds call :func:`check` before a request and :func:`note` after it. A call
is refused when any of:

* the **session cap** (``--max-requests``; :data:`SESSION_CAP_DEFAULT` for an
  ad-hoc run) is reached — the scheduled tasks pass an explicit cap sized from
  :mod:`budget_plan`;
* the provider's **monthly cap** (PulseScore 400, The Odds API 500) would be
  exceeded;
* fewer than :data:`STOP_REMAINING` requests remain this month.

The session counter counts **cost**, not raw calls: PulseScore is 1 per request,
The Odds API is its ``x-requests-last`` header, so the free events endpoints cost
nothing and never eat the cap.

A refusal is logged to ``logs/api_refusals.csv`` (gitignored) and surfaced at the
top of ``reports/health.md``.
"""

from __future__ import annotations

import csv
import sys
from datetime import datetime, timezone
from pathlib import Path

import odds_api_log
import pulsescore_log

SESSION_CAP_DEFAULT = 10
STOP_REMAINING = 50
MONTHLY_CAP = {"pulsescore": 400, "odds_api": 500}

LOG_DIR = Path("logs")
REFUSAL_LOG = LOG_DIR / "api_refusals.csv"
FIELDS = ["timestamp", "provider", "reason", "note"]

_session: dict = {"cap": None, "used": {}}


def start_session(cap: int | None = None) -> None:
    """Begin a run with an explicit per-run cap (defaults to the ad-hoc cap)."""
    _session["cap"] = int(cap) if cap else SESSION_CAP_DEFAULT
    _session["used"] = {}


def _ensure_session() -> None:
    if _session["cap"] is None:
        start_session()


def session_cap() -> int:
    _ensure_session()
    return _session["cap"]


def session_used(provider: str) -> int:
    _ensure_session()
    return int(_session["used"].get(provider, 0))


def monthly_used(provider: str) -> int:
    if provider == "pulsescore":
        return pulsescore_log.used_this_month()
    return odds_api_log.credits_used_this_month()


def check(provider: str) -> tuple[bool, str]:
    """(allowed, reason). Refuses on the session cap, the monthly cap or the reserve."""
    _ensure_session()
    cap = _session["cap"]
    if session_used(provider) >= cap:
        return False, f"session cap {cap} reached ({session_used(provider)} used)"
    used = monthly_used(provider)
    monthly = MONTHLY_CAP[provider]
    if used >= monthly:
        return False, f"monthly cap {monthly} reached ({used} used)"
    remaining = monthly - used
    if remaining < STOP_REMAINING:
        return False, (f"only {remaining} left this month "
                       f"(stop threshold {STOP_REMAINING})")
    return True, ""


def note(provider: str, cost: int = 1) -> None:
    """Record the cost of a call that was actually made."""
    _ensure_session()
    _session["used"][provider] = session_used(provider) + int(cost)


def refuse(provider: str, reason: str, note: str = "") -> None:
    """Log a refused call so the daily health report can show it."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    is_new = not REFUSAL_LOG.exists()
    with REFUSAL_LOG.open("a", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDS)
        if is_new:
            writer.writeheader()
        writer.writerow({
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "provider": provider, "reason": reason, "note": note,
        })


def read_refusals() -> list[dict[str, str]]:
    if not REFUSAL_LOG.exists():
        return []
    with REFUSAL_LOG.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


if __name__ == "__main__":  # pragma: no cover - manual check
    start_session()
    print(f"session cap {session_cap()}")
    for provider in MONTHLY_CAP:
        allowed, reason = check(provider)
        print(f"  {provider}: {'ok' if allowed else reason} "
              f"(month used {monthly_used(provider)}/{MONTHLY_CAP[provider]})")
    sys.exit(0)
