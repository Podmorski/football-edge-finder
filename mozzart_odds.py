"""Mozzart (PulseScore) pre-match odds for the fair sheet and paper trading.

The **global** events feed (``GET /soccer/events``) is the working source on the
free tier. Probed 2026-09-24: the per-league endpoint
(``GET /soccer/leagues/{id}/events``) returns ``{"total": 0, "events": []}`` for
every division we tested (Engleska 1 = 4187, Engleska 4 = 4047, League One =
4080), while the global feed carries those same fixtures under their Serbian
league **label** — "Engleska 4" is League Two and "Engleska 3" is League One,
confirmed by the team names in each label (Cheltenham / Chesterfield sit under
Engleska 4, Plymouth / Burton under Engleska 3). A league is therefore selected
by its label, never by Mozzart's numeric id.

The page size is fixed at **30** (``limit`` is ignored) and the feed is ordered by
kick-off, so a run pages only as far as its window needs and then stops. A pass
costs one request per 30 events — *not* one per league — so the feed is cached on
disk for an hour: every league in a run, and any re-run inside the hour, is
served from that single pass. Only events whose label maps to an in-scope league
are kept, so the cache stays a fraction of the raw feed.

Every call is logged to ``logs/pulsescore_requests.csv`` and counted against the
monthly budget.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

import api_guard
import pulsescore_log
from core import league_registry

BASE = "https://api.pulsescore.net/api/mozzart"
TIMEOUT = 30
THROTTLE_SECONDS = 1.2          # BASIC plan: 1 request/second per bookmaker
PAGE_SIZE = 30                  # fixed by the API; `limit` is ignored
EVENTS_CACHE = Path("data/mozzart/global_events.json")
FEED_STATS = Path("data/mozzart/feed_stats.json")
# A pass costs one request per 30 events, so a re-run within the hour reuses the
# snapshot instead of paying for the feed again (mirrors PS3838's sheet cache).
EVENTS_MAX_AGE_MINUTES = 60

# Mozzart Serbian league name -> our slug, from the wide registry. A league with
# no Mozzart listing (e.g. 2. Bundesliga / Ligue 2 pending listing) is absent.
MOZZART_LEAGUES = league_registry.mozzart_names()

_last_call = [0.0]


def load_key() -> str:
    for line in Path(".env").read_text(encoding="utf-8").splitlines():
        if line.strip().startswith("PULSESCORE_API_KEY="):
            return line.strip().split("=", 1)[1].strip()
    raise SystemExit("PULSESCORE_API_KEY not found in .env")


def _get(session, key, path, params=None, note=""):
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
    pulsescore_log.log_request(endpoint=path, params=params or {},
                               http_status=response.status_code, cost=1, notes=note)
    response.raise_for_status()
    return response.json()


# --------------------------------------------------------------------------- #
# global feed (cached per run window)
# --------------------------------------------------------------------------- #
def _read_cache() -> dict | None:
    if not EVENTS_CACHE.exists():
        return None
    try:
        doc = json.loads(EVENTS_CACHE.read_text(encoding="utf-8"))
        return {"fetched_at": datetime.fromisoformat(doc["fetched_at"]),
                "until": datetime.fromisoformat(doc["until"]) if doc.get("until") else None,
                "total": doc.get("total"), "total_pages": doc.get("total_pages"),
                "events": doc["events"]}
    except (ValueError, KeyError, OSError):
        return None


def _write_cache(fetched_at: datetime, until: datetime | None, events: list[dict],
                 total: int | None, total_pages: int | None) -> None:
    EVENTS_CACHE.parent.mkdir(parents=True, exist_ok=True)
    EVENTS_CACHE.write_text(json.dumps({
        "fetched_at": fetched_at.isoformat(timespec="seconds"),
        "until": until.isoformat(timespec="seconds") if until else None,
        "total": total, "total_pages": total_pages,
        "events": events,
    }, ensure_ascii=False), encoding="utf-8")


def _write_stats(fetched_at: datetime, total: int | None, total_pages: int | None,
                 pages_used: int, events_kept: int) -> None:
    """The last pass's shape, for the daily health report (no API call)."""
    FEED_STATS.parent.mkdir(parents=True, exist_ok=True)
    FEED_STATS.write_text(json.dumps({
        "fetched_at": fetched_at.isoformat(timespec="seconds"),
        "total": total, "total_pages": total_pages,
        "pages_used": pages_used, "events_kept": events_kept,
    }, ensure_ascii=False, indent=2), encoding="utf-8")


def read_stats() -> dict | None:
    if not FEED_STATS.exists():
        return None
    try:
        return json.loads(FEED_STATS.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None


def _covers(cached_until: datetime | None, wanted_until: datetime | None) -> bool:
    """True when a cached feed reaches at least as far as this run needs.

    A cache with no bound holds the whole feed, so it covers any window; a
    window-bounded cache only covers a window that ends no later than it.
    """
    if cached_until is None:
        return True
    if wanted_until is None:
        return False
    return cached_until >= wanted_until


def fetch_global_events(session, key, until: datetime | None = None,
                        max_age_minutes: int | None = EVENTS_MAX_AGE_MINUTES
                        ) -> tuple[list[dict], datetime]:
    """The in-scope events from the global feed, oldest first.

    Pages ``/soccer/events`` (30 events a page) and stops at ``until`` — the feed
    is ordered by kick-off, so everything after the page that crosses ``until`` is
    out of window. Returns ``(events, fetched_at)``; a fresh cached snapshot that
    reaches ``until`` costs no requests.
    """
    cached = _read_cache()
    if cached is not None and max_age_minutes is not None:
        age = datetime.now(timezone.utc) - cached["fetched_at"]
        if age <= timedelta(minutes=max_age_minutes) and _covers(cached["until"], until):
            _write_stats(cached["fetched_at"], cached.get("total"),
                         cached.get("total_pages"), 0, len(cached["events"]))
            return cached["events"], cached["fetched_at"]

    fetched_at = datetime.now(timezone.utc)
    events: list[dict] = []
    page = 1
    total: int | None = None
    total_pages: int | None = None
    while True:
        doc = _get(session, key, "/soccer/events", {"page": page, "limit": PAGE_SIZE},
                   note=f"mozzart global events p{page}")
        batch = [e for e in (doc or {}).get("events", []) if isinstance(e, dict)]
        if total is None and (doc or {}).get("total") is not None:
            total = int(doc["total"])
        if total_pages is None and (doc or {}).get("totalPages"):
            total_pages = int(doc["totalPages"])
        crossed = False
        for event in batch:
            if event.get("league") not in MOZZART_LEAGUES:
                continue
            kickoff = event_kickoff(event)
            if until is not None and kickoff is not None and kickoff >= until:
                crossed = True
                break
            events.append(event)
        if crossed or not batch or (total_pages is not None and page >= total_pages):
            break
        page += 1
    events.sort(key=lambda event: event.get("startTime", ""))
    _write_cache(fetched_at, until, events, total, total_pages)
    _write_stats(fetched_at, total, total_pages, page, len(events))
    return events, fetched_at


def fetch_events(session, key, slugs, until: datetime | None = None,
                 max_age_minutes: int | None = EVENTS_MAX_AGE_MINUTES) -> list[dict]:
    """Upcoming in-scope events for ``slugs``, each stamped ``_slug``/``_fetched_at``.

    The feed is fetched **once** (one pass, cached) and filtered locally by the
    Serbian league label, so the cost does not grow with the number of leagues.
    """
    events, fetched_at = fetch_global_events(session, key, until=until,
                                             max_age_minutes=max_age_minutes)
    stamp = fetched_at.isoformat(timespec="seconds")
    out: list[dict] = []
    for event in events:
        slug = MOZZART_LEAGUES.get(event.get("league", ""))
        if slug is None or slug not in slugs:
            continue
        event["_slug"] = slug
        event["_fetched_at"] = stamp
        out.append(event)
    return out


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
