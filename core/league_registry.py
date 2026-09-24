"""Wide league registry — the single source of truth for the widened run.

Reads ``config/leagues_wide.yaml`` and exposes the mappings every feed needs:

* PS3838 (Pinnacle, the **primary sharp source** via PulseScore) names the
  division in English (``"Germany - Bundesliga"``);
* Mozzart names it in Serbian (``"Nemačka 1"``) and identifies it by a numeric
  ``leagueId``;
* The Odds API key identifies it for the **fallback** odds call and for
  **scores** (``soccer_germany_bundesliga``).

``track`` decides which rule may bet in a league:

* ``MODEL_4L``  — one of our four modelled leagues: model families *and* the
  sharp main line;
* ``SHARP_WIDE`` — the widened set: the sharp main-line rule only.

A league with ``mozzart: null`` cannot produce a flag yet (a flag needs a
Mozzart price); it is listed only so the weekly top-up can pick it up once the
book lists it (``mozzart_pending`` / ``resume_after``).
"""

from __future__ import annotations

import json
from datetime import date
from functools import lru_cache
from pathlib import Path

import yaml

CONFIG = Path("config/leagues_wide.yaml")
TOPUP = Path("data/mozzart/topup.json")
MODEL_4L = "MODEL_4L"
SHARP_WIDE = "SHARP_WIDE"


@lru_cache(maxsize=1)
def leagues() -> tuple[dict, ...]:
    doc = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    out: list[dict] = []
    for entry in doc["leagues"]:
        row = dict(entry)
        row["modelled"] = bool(row.get("modelled", row.get("track") == MODEL_4L))
        out.append(row)
    return tuple(out)


@lru_cache(maxsize=1)
def by_slug() -> dict[str, dict]:
    return {row["slug"]: row for row in leagues()}


@lru_cache(maxsize=1)
def odds_api_sports() -> dict[str, str]:
    """{sport_key: slug} — also what ``fair_sheet.SPORTS`` is built from."""
    return {row["odds_api"]: row["slug"] for row in leagues() if row.get("odds_api")}


@lru_cache(maxsize=1)
def mozzart_names() -> dict[str, str]:
    """{Serbian league name as Mozzart prints it: slug}, for the feeds that list.

    Merges the runtime **top-up** file written by the weekly job when a pending
    division (2. Bundesliga / Ligue 2) finally appears on Mozzart.
    """
    out = {row["mozzart"]: row["slug"] for row in leagues() if row.get("mozzart")}
    for slug, name in topup_overrides().items():
        out[name] = slug
    return out


def topup_overrides() -> dict[str, str]:
    """{slug: Serbian name} added at runtime by the weekly top-up check."""
    if not TOPUP.exists():
        return {}
    try:
        doc = json.loads(TOPUP.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return {}
    return {slug: name for slug, name in doc.items() if isinstance(name, str)}


@lru_cache(maxsize=1)
def ps3838_names() -> dict[str, str]:
    """{PS3838 English league name: slug}."""
    return {row["ps3838"]: row["slug"] for row in leagues() if row.get("ps3838")}


def slug_of(track: str | None = None, modelled: bool | None = None) -> list[str]:
    """Slugs filtered by track and/or modelled flag, in config order."""
    out = []
    for row in leagues():
        if track is not None and row["track"] != track:
            continue
        if modelled is not None and row["modelled"] != modelled:
            continue
        out.append(row["slug"])
    return out


def track_of(slug: str) -> str:
    return by_slug().get(slug, {}).get("track", SHARP_WIDE)


def is_modelled(slug: str) -> bool:
    return bool(by_slug().get(slug, {}).get("modelled"))


def is_active(slug: str) -> bool:
    """True when Mozzart currently lists the league, so a flag is possible."""
    return bool(by_slug().get(slug, {}).get("mozzart")) or slug in topup_overrides()


def ps3838_name(slug: str) -> str | None:
    return by_slug().get(slug, {}).get("ps3838")


def mozzart_name(slug: str) -> str | None:
    return by_slug().get(slug, {}).get("mozzart")


def odds_api_key(slug: str) -> str | None:
    return by_slug().get(slug, {}).get("odds_api")


def pending_topups(today: date | None = None) -> list[tuple[str, str]]:
    """(slug, Mozzart name) for leagues whose Mozzart listing should be re-checked.

    Returns the entries whose ``resume_after`` date has passed and that still have
    no Mozzart name bound, so the weekly job can add them the moment they appear.
    """
    today = today or date.today()
    out: list[tuple[str, str]] = []
    for row in leagues():
        if row.get("mozzart"):
            continue
        name = row.get("mozzart_pending")
        if not name:
            continue
        after = row.get("resume_after")
        if after and date.fromisoformat(str(after)) > today:
            continue
        out.append((row["slug"], name))
    return out