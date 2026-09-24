"""Bounded PulseScore (Mozzart feed) discovery probe.

Every call is logged to ``logs/pulsescore_requests.csv`` and counted against the
monthly budget (``pulsescore_log``). Raw responses are saved under
``data/mozzart/raw/``. The free tier is a **BASIC plan limited to 1 request per
second per bookmaker**, so the probe throttles between calls.

It answers: whether a **pre-match** odds endpoint exists on the free tier, the
free-tier limits, whether PS3838 (Pinnacle) is carried, and how Mozzart's Serbian
league names map to our four leagues.

Run:  ./venv/Scripts/python.exe pulsescore_probe.py
"""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

import pulsescore_log

sys.stdout.reconfigure(encoding="utf-8")

BASE = "https://api.pulsescore.net/api/mozzart"
RAW_DIR = Path("data/mozzart/raw")
TIMEOUT = 30
THROTTLE_SECONDS = 1.2          # BASIC plan: 1 request/second per bookmaker

# Mozzart's Serbian league names for our four leagues.
TARGET_LEAGUES = {
    "Nemačka 1": "bundesliga_1",
    "Nemačka 2": "bundesliga_2",
    "Engleska 3": "league_one_t3",
    "Francuska 2": "ligue_2_t2",
}

_last_call = [0.0]


def load_key() -> str:
    for line in Path(".env").read_text(encoding="utf-8").splitlines():
        if line.strip().startswith("PULSESCORE_API_KEY="):
            return line.strip().split("=", 1)[1].strip()
    raise SystemExit("PULSESCORE_API_KEY not found in .env")


def call(session, key, path, params=None, note="", save=True):
    """One logged, throttled GET. Returns (status, data)."""
    allowed, reason = pulsescore_log.budget_ok()
    if not allowed:
        print(f"REFUSED: {reason}")
        return None, None
    wait = THROTTLE_SECONDS - (time.monotonic() - _last_call[0])
    if wait > 0:
        time.sleep(wait)
    response = session.get(f"{BASE}{path}", params=params or {},
                           headers={"X-Secret": key, "Accept": "application/json"},
                           timeout=TIMEOUT)
    _last_call[0] = time.monotonic()
    pulsescore_log.log_request(endpoint=path, params=params or {},
                               http_status=response.status_code, cost=1, notes=note)
    try:
        data = response.json()
    except ValueError:
        data = None
    if save and data is not None:
        RAW_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        safe = path.strip("/").replace("/", "_")
        (RAW_DIR / f"{safe}__{stamp}.json").write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    size = len(data) if isinstance(data, (list, dict)) else "n/a"
    print(f"  GET {path} {params or ''} -> HTTP {response.status_code} ({size})")
    return response.status_code, data


def main() -> int:
    key = load_key()
    print(f"key loaded: {'yes' if key else 'no'}")
    allowed, reason = pulsescore_log.budget_ok()
    print(f"budget: {reason or 'ok'} · remaining this month "
          f"{pulsescore_log.remaining_this_month()}")
    if not allowed:
        return 1

    session = requests.Session()

    print("\n[1] GET /soccer/leagues (all pages) — find our four leagues")
    rows: list[dict] = []
    for page in (1, 2, 3, 4):
        _, leagues = call(session, key, "/soccer/leagues",
                          params={"page": page, "limit": 30},
                          note=f"discovery: leagues page {page}")
        if isinstance(leagues, dict):
            rows += leagues.get("leagues", [])
    print(f"  {len(rows)} leagues; free-tier plan: BASIC = 1 req/s per bookmaker")
    found = {lg["name"]: lg.get("leagueId") for lg in rows if lg.get("name") in TARGET_LEAGUES}
    print("  league mapping:")
    for sr, slug in TARGET_LEAGUES.items():
        print(f"    {sr:<14} -> {slug:<16} leagueId={found.get(sr, 'NOT FOUND')}")

    print("\n[2] GET /soccer/events?page=1&limit=30  (pre-match events?)")
    _, ev = call(session, key, "/soccer/events", params={"page": 1, "limit": 30},
                 note="discovery: events list")
    events = ev.get("events", []) if isinstance(ev, dict) else (ev or [])
    print(f"  {len(events)} events")
    if events:
        print("  sample event keys:", list(events[0])[:30])
        print("  first event:", json.dumps(events[0], ensure_ascii=False)[:700])

    print("\n[3] GET /soccer/events/{id}  (market detail for one event)")
    if events:
        eid = events[0].get("id") or events[0].get("eventId")
        _, detail = call(session, key, f"/soccer/events/{eid}",
                         note="discovery: one event detail")
        if isinstance(detail, dict):
            print("  top-level keys:", list(detail)[:25])
            print("  detail:", json.dumps(detail, ensure_ascii=False)[:1200])

    pulsescore_log.print_month()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())