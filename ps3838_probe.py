"""Bounded PS3838 (Pinnacle) discovery probe on the PulseScore feed.

PS3838 is the sharp book this project anchors on. The same PulseScore key that
carries the Mozzart feed exposes a PS3838 feed under a *different* base path
(``/api/ps3838``). This probe answers, with the fewest possible requests, the
questions the fair sheet needs:

* which leagues PS3838 carries for our four divisions (and their league ids);
* whether a **pre-match** events feed with prices exists;
* the event / market JSON shape (so the parser is written against the real feed,
  never a guess).

Every call goes through :mod:`pulsescore_log`, so it counts against the monthly
budget and is throttled to the BASIC plan's 1 request/second.

Run:  ./venv/Scripts/python.exe ps3838_probe.py
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

BASE = "https://api.pulsescore.net/api/ps3838"
RAW_DIR = Path("data/ps3838/raw")
TIMEOUT = 30
THROTTLE_SECONDS = 1.2          # BASIC plan: 1 request/second per bookmaker

# What we call each division, and the name fragments PS3838 is expected to use.
TARGET_HINTS = {
    "bundesliga_1": "Germany Bundesliga",
    "bundesliga_2": "Germany Bundesliga 2",
    "league_one_t3": "England League One",
    "ligue_2_t2": "France Ligue 2",
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

    print("\n[1] GET /soccer/leagues (all pages) — locate our four divisions")
    rows: list[dict] = []
    for page in (1, 2, 3, 4):
        status, doc = call(session, key, "/soccer/leagues",
                           params={"page": page, "limit": 30},
                           note=f"ps3838 discovery: leagues page {page}")
        if isinstance(doc, dict):
            rows += doc.get("leagues", [])
        elif isinstance(doc, list):
            rows += doc
        if not rows and status and status >= 400:
            break
    print(f"  {len(rows)} leagues")
    hits = [(lg.get("name"), lg.get("leagueId")) for lg in rows
            if any(hint.lower() in str(lg.get("name", "")).lower()
                   for hint in TARGET_HINTS.values())]
    for name, lid in hits:
        print(f"    {name:<32} leagueId={lid}")

    print("\n[2] GET /soccer/events?page=1&limit=30  (pre-match events + prices?)")
    _, ev = call(session, key, "/soccer/events", params={"page": 1, "limit": 30},
                 note="ps3838 discovery: events list")
    events = ev.get("events", []) if isinstance(ev, dict) else (ev or [])
    print(f"  {len(events)} events")
    if events:
        print("  sample event keys:", list(events[0])[:30])
        print("  first event:", json.dumps(events[0], ensure_ascii=False)[:900])

    print("\n[3] GET /soccer/events/{id}  (market detail for one event)")
    if events:
        eid = events[0].get("id") or events[0].get("eventId")
        _, detail = call(session, key, f"/soccer/events/{eid}",
                         note="ps3838 discovery: one event detail")
        if isinstance(detail, dict):
            print("  top-level keys:", list(detail)[:25])
            print("  detail:", json.dumps(detail, ensure_ascii=False)[:1500])

    pulsescore_log.print_month()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())