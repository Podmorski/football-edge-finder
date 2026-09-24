"""Results for the widened leagues — The Odds API **scores** endpoint.

The four modelled leagues settle from the free football-data.co.uk history we
already hold (``bet_log.find_result``). The **widened** leagues have no such
local history, so PART A assigns The Odds API its second role: **scores**.

The endpoint is called **once per league per day** and cached on disk, only for
a league that actually has an unsettled paper bet, so the cost is bounded by the
number of widened leagues that settle on a given day. ``daysFrom=3`` covers the
weekend plus stragglers; the response gives the final score only (home/away),
which is exactly what the sharp full-time families need — the half-time markets
are model families and settle from local history instead.

Every call is logged to ``logs/odds_api_requests.csv``.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests

import fair_sheet as fs
import odds_api_log
from core import league_registry
from core.team_names import MATCH_SIMILARITY, similarity

BASE = "https://api.the-odds-api.com/v4"
CACHE_DIR = Path("data/odds_snapshots/oddsapi/scores")
DAYS_FROM = 3


class ScoresRow:
    """A result row with only full-time goals; half-time is never used by the
    sharp families that settle this way."""

    def __init__(self, fthg: int, ftag: int):
        self.fthg = fthg
        self.ftag = ftag
        self.hthg = 0
        self.htag = 0


def _cache_path(sport_key: str, when: date) -> Path:
    return CACHE_DIR / f"{sport_key}_{when.isoformat()}.json"


def _cached(sport_key: str, when: date):
    path = _cache_path(sport_key, when)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None


def _save(sport_key: str, when: date, events) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    _cache_path(sport_key, when).write_text(
        json.dumps(events, ensure_ascii=False), encoding="utf-8")


def _call_scores(sport_key: str, when: date, session, key: str):
    cached = _cached(sport_key, when)
    if cached is not None:
        return cached, 0
    if session is None:
        session = requests.Session()
    response = session.get(
        f"{BASE}/sports/{sport_key}/scores/",
        params={"apiKey": key, "daysFrom": DAYS_FROM},
        timeout=30,
    )
    odds_api_log.log_request(
        endpoint=f"/sports/{sport_key}/scores/", params={"daysFrom": DAYS_FROM},
        http_status=response.status_code,
        cost=response.headers.get("x-requests-last", ""),
        used=response.headers.get("x-requests-used", ""),
        remaining=response.headers.get("x-requests-remaining", ""),
        notes="paper-settle scores (widened leagues)",
    )
    try:
        data = response.json()
    except ValueError:
        return None, 0
    cost = int(float(response.headers.get("x-requests-last") or 0))
    if response.status_code == 200 and isinstance(data, list):
        _save(sport_key, when, data)
        return data, cost
    return None, cost


def find_result(slug: str, when: date, home: str, away: str,
                session=None, key: str | None = None):
    """A :class:`ScoresRow` for a finished widened-league match, else None."""
    sport_key = league_registry.odds_api_key(slug)
    if sport_key is None:
        return None
    try:
        key = key or fs.load_key()
        events, _cost = _call_scores(sport_key, when, session, key)
    except Exception:  # noqa: BLE001
        return None
    if not events:
        return None
    best = None
    for event in events:
        if not event.get("completed"):
            continue
        if similarity(home, event.get("home_team", "")) < MATCH_SIMILARITY:
            continue
        if similarity(away, event.get("away_team", "")) < MATCH_SIMILARITY:
            continue
        scores = {s.get("name"): s.get("score") for s in event.get("scores") or []}
        hs = scores.get(event.get("home_team"))
        as_ = scores.get(event.get("away_team"))
        if hs is None or as_ is None:
            continue
        try:
            row = ScoresRow(int(hs), int(as_))
        except (TypeError, ValueError):
            continue
        best = row
        break
    return best