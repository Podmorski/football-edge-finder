"""PS3838 (Pinnacle) via PulseScore — the **primary sharp source**.

The fair sheet anchors on PS3838's pre-match 1X2 and totals. This module reads
PS3838 from the same PulseScore key as the Mozzart feed, under a different base
path (``/api/ps3838``), so the sharp and soft snapshots are taken in the **same
run**, minutes apart (the join rejects a pair more than

``config/paper.yaml:max_snapshot_gap_minutes`` apart as STALE).

Feed shape (probed 2026-09-24, ``ps3838_probe.py``):

* ``GET /soccer/leagues``                       -> 120 divisions, ``name`` only;
* ``GET /soccer/leagues/{url-encoded name}/events`` -> ``{"total", "events": [...]}``
  — the *only* way to scope to a division (the global feed is 854 events over
  29 pages, and every query param except ``page``/``limit`` is ignored);
* each event: ``eventId``, ``home``, ``away``, ``league``, ``startTime``,
  ``updatedAt``, ``markets[]`` with ``canonicalMarket`` in
  ``{MATCH_RESULT, OVER_UNDER, ASIAN_HANDICAP}``, a ``line``, a ``period`` and
  ``moreInfo.isMainLine``.

Every request is logged to ``logs/pulsescore_requests.csv`` and counted against
the monthly budget. A **per-league snapshot is cached on disk**: a league whose
cached fixtures show nothing in the run's window costs **zero** requests, which
is what keeps the widened set inside the budget.
"""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import requests

import api_guard
import pulsescore_log
from core import league_registry

BASE = "https://api.pulsescore.net/api/ps3838"
TIMEOUT = 30
THROTTLE_SECONDS = 1.2          # BASIC plan: 1 request/second per bookmaker

CACHE_DIR = Path("data/ps3838/leagues")
SCHEDULE_TTL_DAYS = 7           # after this a league is refetched regardless

_last_call = [0.0]


def load_key() -> str:
    for line in Path(".env").read_text(encoding="utf-8").splitlines():
        if line.strip().startswith("PULSESCORE_API_KEY="):
            return line.strip().split("=", 1)[1].strip()
    raise SystemExit("PULSESCORE_API_KEY not found in .env")


def _get(session, key, path, params=None, note="") -> dict | None:
    allowed, reason = api_guard.check("pulsescore")
    if not allowed:
        api_guard.refuse("pulsescore", reason, note or path)
        raise RuntimeError(f"PulseScore budget: {reason}")
    wait = THROTTLE_SECONDS - (time.monotonic() - _last_call[0])
    if wait > 0:
        time.sleep(wait)
    response = session.get(f"{BASE}{path}", params=params or {},
                           headers={"X-Secret": key, "Accept": "application/json"},
                           timeout=TIMEOUT)
    _last_call[0] = time.monotonic()
    api_guard.note("pulsescore")
    pulsescore_log.log_request(endpoint=f"/api/ps3838{path}", params=params or {},
                               http_status=response.status_code, cost=1, notes=note)
    try:
        data = response.json()
    except ValueError:
        data = None
    if response.status_code >= 400:
        return None
    return data if isinstance(data, dict) else None


# --------------------------------------------------------------------------- #
# per-league snapshots (cache + schedule gate)
# --------------------------------------------------------------------------- #
def _cache_path(slug: str) -> Path:
    return CACHE_DIR / f"{slug}.json"


def load_cached(slug: str) -> dict | None:
    """{"fetched_at": datetime, "events": [...]} for the league, or None."""
    path = _cache_path(slug)
    if not path.exists():
        return None
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
        return {"fetched_at": datetime.fromisoformat(doc["fetched_at"]),
                "events": doc["events"]}
    except (ValueError, KeyError, OSError):
        return None


def _save_cached(slug: str, events: list[dict]) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    _cache_path(slug).write_text(
        json.dumps({"fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    "events": events}, ensure_ascii=False), encoding="utf-8")


def fetch_league(session, key, slug: str, max_age_minutes: int | None = None
                 ) -> tuple[list[dict], datetime]:
    """PS3838 events for one division (1 request unless a fresh cache is reused).

    ``max_age_minutes=None`` always makes the request (the close run wants the
    freshest price); a number reuses the on-disk snapshot when it is younger than
    that, so back-to-back sheet runs inside the window cost no requests.
    """
    name = league_registry.ps3838_name(slug)
    if name is None:
        return [], datetime.now(timezone.utc)
    if max_age_minutes is not None:
        cached = load_cached(slug)
        if cached is not None and (datetime.now(timezone.utc) - cached["fetched_at"]
                                   ) <= timedelta(minutes=max_age_minutes):
            return cached["events"], cached["fetched_at"]
    doc = _get(session, key, f"/soccer/leagues/{name}/events", {},
               note=f"ps3838 events {slug}")
    events = [e for e in (doc or {}).get("events", []) if isinstance(e, dict)]
    events.sort(key=lambda e: e.get("startTime", ""))
    _save_cached(slug, events)
    return events, datetime.now(timezone.utc)


def cached_events(slug: str, ttl_days: int = SCHEDULE_TTL_DAYS) -> list[dict] | None:
    """Cached fixtures for a league, or None when missing/stale.

    A stale cache forces a refetch so the schedule never silently goes empty.
    """
    cached = load_cached(slug)
    if cached is None:
        return None
    if datetime.now(timezone.utc) - cached["fetched_at"] > timedelta(days=ttl_days):
        return None
    return cached["events"]


def event_kickoff(event: dict) -> datetime | None:
    raw = event.get("startTime")
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def has_fixture_in(events: list[dict], start: datetime, end: datetime) -> bool:
    """True when any event kicks off in ``[start, end)`` (both UTC-aware)."""
    for event in events or []:
        kickoff = event_kickoff(event)
        if kickoff is not None and start <= kickoff < end:
            return True
    return False


# --------------------------------------------------------------------------- #
# sharp prices
# --------------------------------------------------------------------------- #
def _main_market(event: dict, canonical: str, period: str = "FULL_TIME") -> dict | None:
    """The main line of a canonical market, falling back to any line of it."""
    candidates = [m for m in event.get("markets", [])
                  if m.get("canonicalMarket") == canonical and m.get("period") == period
                  and m.get("isActive", True)]
    if not candidates:
        return None
    main = [m for m in candidates if (m.get("moreInfo") or {}).get("isMainLine")]
    return (main or candidates)[0]


def _outcomes(market: dict) -> dict[str, float]:
    out: dict[str, float] = {}
    for selection in market.get("selections", []):
        if not selection.get("isActive", True):
            continue
        odds = selection.get("odds")
        name = selection.get("canonicalOutcome") or selection.get("rawName")
        if isinstance(odds, (int, float)) and odds > 1.0 and name:
            out[str(name).upper()] = float(odds)
    return out


def sharp_prices(event: dict) -> dict | None:
    """De-margined PS3838 1X2 + the counters totals line nearest 2.5.

    Mirrors :func:`fair_sheet.pinnacle_prices` exactly (same keys, power
    de-margin), so the anchor solver and the flags code are source-agnostic.
    Returns None when the event carries no usable 1X2 or totals line.
    """
    from core import odds as odds_mod

    mr = _main_market(event, "MATCH_RESULT")
    if mr is None:
        return None
    names = _outcomes(mr)
    if not {"HOME", "DRAW", "AWAY"} <= set(names):
        return None
    raw_1x2 = np.array([names["HOME"], names["DRAW"], names["AWAY"]], dtype=float)
    p_1x2 = odds_mod.demargin(pd.DataFrame([raw_1x2]), "power").to_numpy()[0]

    ou_markets = [m for m in event.get("markets", [])
                  if m.get("canonicalMarket") == "OVER_UNDER"
                  and m.get("period") == "FULL_TIME" and m.get("isActive", True)]
    lines: dict[float, dict[str, float]] = {}
    for market in ou_markets:
        side = _outcomes(market)
        if {"OVER", "UNDER"} <= set(side):
            lines[float(market.get("line"))] = side
    if not lines:
        return None
    point = min(lines, key=lambda pt: (abs(pt - 2.5), pt))
    raw_ou = np.array([lines[point]["OVER"], lines[point]["UNDER"]], dtype=float)
    p_ou = odds_mod.demargin(pd.DataFrame([raw_ou]), "power").to_numpy()[0]

    # Every full-time totals line, de-margined: a GOAL_RANGE_FT threshold that
    # matches one of these is priced DIRECTLY off the sharp line, not the grid.
    all_lines: dict[float, dict[str, float]] = {}
    for pt, side in lines.items():
        raw = np.array([side["OVER"], side["UNDER"]], dtype=float)
        p = odds_mod.demargin(pd.DataFrame([raw]), "power").to_numpy()[0]
        all_lines[float(pt)] = {"over": float(p[0]), "under": float(p[1])}

    return {
        "p_home": float(p_1x2[0]), "p_draw": float(p_1x2[1]), "p_away": float(p_1x2[2]),
        "p_over": float(p_ou[0]), "line": float(point),
        "raw_1x2": [float(x) for x in raw_1x2], "raw_ou": [float(x) for x in raw_ou],
        "margin_1x2": float((1.0 / raw_1x2).sum() - 1.0),
        "margin_ou": float((1.0 / raw_ou).sum() - 1.0),
        "totals": all_lines,
        "snapshot": event.get("updatedAt") or (mr.get("updatedAt") or ""),
    }


def normalize(event: dict, slug: str) -> dict | None:
    """The sheet's internal event shape from a PS3838 event."""
    kickoff = event_kickoff(event)
    if kickoff is None or not event.get("home") or not event.get("away"):
        return None
    return {
        "event_id": str(event.get("eventId") or ""),
        "league": slug,
        "home": event["home"],
        "away": event["away"],
        "kickoff": kickoff.isoformat(),
        "prices": sharp_prices(event),
        "source": "ps3838",
    }


def closing_prices(home: str, away: str, when) -> dict | None:
    """The de-margined sharp price for a match from the freshest cached snapshot."""
    from core.team_names import MATCH_SIMILARITY, similarity

    best: tuple[datetime, dict] | None = None
    for row in league_registry.leagues():
        cached = load_cached(row["slug"])
        if cached is None:
            continue
        for event in cached["events"]:
            kickoff = event_kickoff(event)
            if kickoff is None or kickoff.astimezone().date() != when:
                continue
            if similarity(home, event.get("home", "")) < MATCH_SIMILARITY:
                continue
            if similarity(away, event.get("away", "")) < MATCH_SIMILARITY:
                continue
            if best is None or cached["fetched_at"] > best[0]:
                best = (cached["fetched_at"], event)
    return sharp_prices(best[1]) if best else None


if __name__ == "__main__":  # pragma: no cover - manual smoke check
    _key = load_key()
    _session = requests.Session()
    _slug = sys.argv[1] if len(sys.argv) > 1 else "bundesliga_1"
    _events, _when = fetch_league(_session, _key, _slug)
    print(f"{_slug}: {len(_events)} events at {_when.isoformat()}")
    for _e in _events[:3]:
        _p = sharp_prices(_e)
        print(f"  {_e['home']} vs {_e['away']} @ {_e['startTime']} "
              f"-> {'priced' if _p else 'no sharp price'}")