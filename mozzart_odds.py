"""Mozzart (PulseScore) pre-match odds for the fair sheet and paper trading.

Fetches the upcoming-events feed (throttled to the BASIC plan's 1 request per
second) and maps each selection to a catalogue market through
:mod:`core.mozzart_map`. Only the leagues the wide registry lists (and that
Mozzart currently names) are kept. Every call is logged to
``logs/pulsescore_requests.csv`` and counted against the monthly budget.

The feed returns **pre-match** events (``live: false``) with their full market
list, so no live WebSocket is needed.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

import pulsescore_log
from core import league_registry

BASE = "https://api.pulsescore.net/api/mozzart"
TIMEOUT = 30
THROTTLE_SECONDS = 1.2          # BASIC plan: 1 request/second per bookmaker
LEAGUE_CACHE = Path("data/mozzart/league_ids.json")
LEAGUE_CACHE_DAYS = 7

# Mozzart Serbian league name -> our slug, from the wide registry. A league with
# no Mozzart listing (e.g. 2. Bundesliga / Ligue 2 pending listing) is absent.
MOZZART_LEAGUES = league_registry.mozzart_names()
# The league ids seen in the discovery run (2026-09-24). Nemačka 2 / Francuska 2
# were absent from the feed then; they are re-resolved from the league list.
KNOWN_LEAGUE_IDS = {
    "bundesliga_1": "4143",
    "league_one_t3": "4080",
}

_last_call = [0.0]


def load_key() -> str:
    for line in Path(".env").read_text(encoding="utf-8").splitlines():
        if line.strip().startswith("PULSESCORE_API_KEY="):
            return line.strip().split("=", 1)[1].strip()
    raise SystemExit("PULSESCORE_API_KEY not found in .env")


def _get(session, key, path, params=None, note=""):
    allowed, reason = pulsescore_log.budget_ok()
    if not allowed:
        raise RuntimeError(f"PulseScore budget: {reason}")
    wait = THROTTLE_SECONDS - (time.monotonic() - _last_call[0])
    if wait > 0:
        time.sleep(wait)
    response = session.get(f"{BASE}{path}", params=params or {},
                           headers={"X-Secret": key, "Accept": "application/json"},
                           timeout=TIMEOUT)
    _last_call[0] = time.monotonic()
    pulsescore_log.log_request(endpoint=path, params=params or {},
                               http_status=response.status_code, cost=1, notes=note)
    response.raise_for_status()
    return response.json()


def league_ids(session, key) -> dict[str, str]:
    """{slug: leagueId} for the in-scope leagues, cached on disk for a week.

    The league list is 4 pages; caching it keeps a normal run to one request per
    mapped league instead of five.
    """
    if LEAGUE_CACHE.exists():
        try:
            doc = json.loads(LEAGUE_CACHE.read_text(encoding="utf-8"))
            fetched = datetime.fromisoformat(doc["fetched_at"])
            if datetime.now(timezone.utc) - fetched < timedelta(days=LEAGUE_CACHE_DAYS):
                return dict(doc["ids"])
        except (ValueError, KeyError, OSError):
            pass

    out: dict[str, str] = {}
    for page in (1, 2, 3, 4):
        doc = _get(session, key, "/soccer/leagues", {"page": page, "limit": 30},
                   note="mozzart league list")
        for league in doc.get("leagues", []):
            slug = MOZZART_LEAGUES.get(league.get("name", ""))
            if slug:
                out[slug] = str(league.get("leagueId"))
    LEAGUE_CACHE.parent.mkdir(parents=True, exist_ok=True)
    LEAGUE_CACHE.write_text(json.dumps(
        {"fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
         "ids": out}, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


def fetch_events(session, key, ids: dict[str, str]) -> list[dict]:
    """Upcoming events for the in-scope leagues, each stamped with ``_fetched_at``."""
    fetched = datetime.now(timezone.utc).isoformat(timespec="seconds")
    events: list[dict] = []
    for slug, league_id in ids.items():
        doc = _get(session, key, f"/soccer/leagues/{league_id}/events", {},
                   note=f"mozzart events {slug}")
        for event in doc.get("events", []):
            event["_slug"] = slug
            event["_fetched_at"] = fetched
            events.append(event)
    return events


def market_odds(event: dict) -> dict[tuple[str, str], dict]:
    """{(family, code): {odds, section, code, description}} for one Mozzart event.

    Only selections that map to a catalogue market are returned; the rest are
    UNMAPPED and simply absent (never guessed).
    """
    from core.mozzart_map import resolve

    out: dict[tuple[str, str], dict] = {}
    for market in event.get("markets", []):
        section = market.get("rawName", "")
        period = market.get("period", "")
        for selection in market.get("selections", []):
            if not selection.get("isActive", True):
                continue
            code = selection.get("rawName", "")
            mapped = resolve(section, period, code)
            if mapped is None:
                continue
            odds = selection.get("odds")
            if not isinstance(odds, (int, float)) or odds <= 1.0:
                continue
            out[(mapped.family, mapped.code)] = {
                "odds": float(odds),
                "section": section,
                "code": code,
                "description": (selection.get("moreInfo") or {}).get("description", ""),
            }
    return out


def event_kickoff(event: dict) -> datetime | None:
    raw = event.get("startTime")
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None