"""Daily fair-odds sheet, anchored on the sharp (Pinnacle) pre-match price.

The user checks value **at the book they already use** and never enters a price
by hand: the sheet states, per market, the fair odds and the **minimum acceptable
odds** = fair odds x 1.035. If the local price is at or above the minimum, the bet
clears the cushion.

Pipeline
--------
1. ``GET /sports/{key}/events`` (free) for the four sport keys, filtered to a
   local-date window.
2. ``GET /sports/{key}/odds`` with ``regions=eu, markets=h2h,totals,
   bookmakers=pinnacle`` — 2 credits per match, **cached per match for 6 hours**.
   Hard cap 60 credits per run; stop early when the account drops below 100.
3. De-margin Pinnacle's h2h and totals with the **power** method and solve the
   ``(lambda, mu)`` anchor so the L1 grid reproduces them exactly (the totals
   line, whatever it is, is passed through to the anchor).
4. Price every market in the catalogue and every market in the catalogue's
   ``ext_markets`` section through the half model.

What is shown
-------------
Families whose calibration status is **PASS**, plus the four **main-line**
families (RESULT, DOUBLE_CHANCE, GOAL_RANGE_FT, NO_BET) whose price is the sharp
anchor itself. UNTESTABLE and UNCONFIRMED markets are never shown. Rows are
de-duplicated by settlement identity, so a market that two codes describe
identically appears once.

``odds move — re-run within ~1h of betting``: the anchor is only as fresh as the
snapshot printed at the top of the sheet.
"""

from __future__ import annotations

import csv
import json
import sys
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import requests
import yaml

import odds_api_log
import step4_pricing
from core import odds
from core.half_model import (
    MAX_HALF_GOALS,
    batch_market_probs,
    fair_odds,
    grids_to_flat,
    joint_grid,
    market_masks,
    solve_anchor,
)
from core.team_names import MATCH_SIMILARITY, similarity

from step1_catalogue import settlement_signature

BASE = "https://api.the-odds-api.com/v4"
REGION = "eu"
BOOKMAKER = "pinnacle"
ODDS_MARKETS = "h2h,totals"
SPORTS = {
    "soccer_germany_bundesliga": "bundesliga_1",
    "soccer_germany_bundesliga2": "bundesliga_2",
    "soccer_england_league1": "league_one_t3",
    "soccer_france_ligue_two": "ligue_2_t2",
}
CREDIT_CAP = 60
MIN_REMAINING = 100
CACHE_HOURS = 6
EDGE_CUSHION = 1.035
MAX_HALF = MAX_HALF_GOALS

CACHE_DIR = Path("data/odds_snapshots/oddsapi/fair_sheet")
SHEET_DIR = Path("reports/fair_sheets")
SUMMARY_CSV = SHEET_DIR / "summary.csv"
PAPER_CONFIG = Path("config/paper.yaml")

# Families whose price is a SHARP main-line market, eligible for a Mozzart flag
# even without a calibration verdict. NO_BET counts only for the full-time pair.
FLAG_SHARP_FAMILIES = {"RESULT", "DOUBLE_CHANCE", "GOAL_RANGE_FT"}
FLAG_SHARP_CODES = {("NO_BET", "XNB FT 1"), ("NO_BET", "XNB FT 2")}

# How far apart a Mozzart event and a fair-sheet match may kick off and still be
# treated as the same fixture.
KICKOFF_TOLERANCE_HOURS = 6

# Rows read straight off the sharp price rather than off a model:
# RESULT, DOUBLE_CHANCE and the full-time No-Bet pair are exact functions of the
# de-margined sharp 1X2, and GOAL_RANGE_FT is the anchored score grid's
# implication of the sharp 1X2 + totals line. Their status is SHARP, never a
# calibration verdict.
SHARP_FAMILIES = {"RESULT", "DOUBLE_CHANCE", "GOAL_RANGE_FT"}
SHARP_CODES = {("NO_BET", "XNB FT 1"), ("NO_BET", "XNB FT 2")}

# Typical Serbian-book margin per family, and the basis of each number: the margin
# of the CHEAPEST exhaustive partition in the sample capture. The partitions the
# report already measures are marked §3 (reports/phase3_soccerbet_sample.md); the
# goal-range and No-Bet two-way partitions are recorded in that report's appendix.
# The book charges least on the low-margin families, so their rows come first.
FAMILY_MARGIN = {
    "GOAL_RANGE_FT": 0.0779,    # Ukupno Golova 0-2 / 3+
    "GOAL_RANGE_2H": 0.0779,    # II Pol. Uk. Golova 0-2 / 3+
    "GOAL_RANGE_1H": 0.0808,    # I Pol. Uk. Golova 0-1 / 2+
    "RESULT": 0.0856,           # report §3
    "DOUBLE_CHANCE": 0.0901,    # report §3
    "NO_BET": 0.1105,           # X No Bet 1 / 2, draw voids
    "HALF_RESULT": 0.1327,      # report §3 (cheapest of 1H / 2H)
    "MORE_GOALS_HALF": 0.1365,  # report §3
    "HALF_DC": 0.1370,          # report §3 (cheapest of 1H / 2H)
    "HTFT": 0.1990,             # report §3
    "HTFT_NE": 0.1990,          # same displayed section as HTFT: Poluvreme/Kraj
    "HTFT_DC": 0.1990,          # same displayed section as HTFT: Poluvreme/Kraj
}
MARGIN_UNKNOWN = 1.0            # no exhaustive partition in the sample: sorts last

# Presentation: a short, phone-readable shortlist per match. The 15 rows are
# spread **evenly across families** (round-robin, cheapest family first), so a
# family with many prices cannot crowd the others out.
MAX_ROWS = 15

_MARKETS_CACHE: list | None = None
_MASKS_CACHE: dict | None = None


# --------------------------------------------------------------------------- #
# markets and masks (built once per process)
# --------------------------------------------------------------------------- #
def sheet_markets():
    """Catalogue + ext markets, each with the key it is printed under.

    Base markets are keyed by their bare code; ext markets by ``PREFIX:code``,
    the form Soccer Bet prints (and the only unambiguous one — ``1`` is a result
    under ``FT`` but exactly one goal under ``T``).
    """
    global _MARKETS_CACHE
    if _MARKETS_CACHE is None:
        out = [(m.code, m) for m in step4_pricing.load_markets()]
        out += [(f"{m.prefix}:{m.code}", replace(m, code=f"{m.prefix}:{m.code}"))
                for m in step4_pricing.load_ext_markets()]
        _MARKETS_CACHE = out
    return _MARKETS_CACHE


def masks() -> dict:
    global _MASKS_CACHE
    if _MASKS_CACHE is None:
        _MASKS_CACHE = market_masks([m for _, m in sheet_markets()], MAX_HALF)
    return _MASKS_CACHE


def family_status() -> dict[str, str]:
    return step4_pricing.family_status()


def load_paper_config() -> dict:
    """Paper-trading knobs (payout factor, cushion, haircut, snapshot gap)."""
    doc = yaml.safe_load(PAPER_CONFIG.read_text(encoding="utf-8"))
    return {
        "payout_factor": float(doc.get("bookmaker_payout_factor", 1.0)),
        "stake_fee": float(doc.get("stake_fee", 0.0)),
        "edge_cushion": float(doc.get("edge_cushion", EDGE_CUSHION)),
        "ev_haircut": float(doc.get("ev_haircut", 0.20)),
        "max_gap_minutes": float(doc.get("max_snapshot_gap_minutes", 60)),
        "stake": float(doc.get("stake", 1.0)),
        "min_paper_bets": int(doc.get("min_paper_bets", 50)),
    }


# --------------------------------------------------------------------------- #
# The Odds API
# --------------------------------------------------------------------------- #
def load_key() -> str:
    for line in Path(".env").read_text(encoding="utf-8").splitlines():
        if line.strip().startswith("ODDS_API_KEY="):
            return line.strip().split("=", 1)[1].strip()
    raise SystemExit("ODDS_API_KEY not found in .env")


def _call(session, key, path, params=None, note=""):
    query = {"apiKey": key}
    if params:
        query.update(params)
    response = session.get(f"{BASE}{path}", params=query, timeout=30)
    odds_api_log.log_request(
        endpoint=path, params=params or {}, http_status=response.status_code,
        cost=response.headers.get("x-requests-last", ""),
        used=response.headers.get("x-requests-used", ""),
        remaining=response.headers.get("x-requests-remaining", ""),
        notes=note,
    )
    try:
        data = response.json()
    except ValueError:
        data = None
    return data, response.headers


def _remaining(headers) -> int | None:
    value = headers.get("x-requests-remaining")
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def upcoming_events(session, key, window: set[date]) -> tuple[list[tuple[str, dict]], dict, int]:
    """(sport_key, event) pairs whose LOCAL date is in ``window`` and are unplayed.

    Started matches are skipped: they cannot be bet, and their price is no longer a
    pre-match price, so spending credits on them would be wasteful and misleading.
    """
    out: list[tuple[str, dict]] = []
    headers: dict = {}
    started = 0
    now = datetime.now(timezone.utc)
    for sport_key, slug in SPORTS.items():
        data, headers = _call(session, key, f"/sports/{sport_key}/events", note="fair-sheet events (free)")
        for event in data if isinstance(data, list) else []:
            if local_date(event["commence_time"]) not in window:
                continue
            if kickoff_utc(event["commence_time"]) <= now:
                started += 1
                continue
            out.append((sport_key, event))
    out.sort(key=lambda item: item[1]["commence_time"])
    return out, headers, started


def kickoff_utc(iso: str) -> datetime:
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(timezone.utc)


def local_date(iso: str) -> date:
    """The kickoff date the user sees (local), from an ISO-8601 UTC string."""
    return kickoff_utc(iso).astimezone().date()


def cached(event_id: str) -> dict | None:
    """The newest snapshot for the event if it is still inside the cache window."""
    history = snapshot_history(event_id)
    if not history:
        return None
    fetched, data = history[-1]
    if datetime.now(timezone.utc) - fetched > timedelta(hours=CACHE_HOURS):
        return None
    return data


def snapshot_history(event_id: str | None = None) -> list[tuple[datetime, dict]]:
    """Every snapshot we hold, oldest first, as ``(fetched_at, data)``.

    Snapshots are **append-only** (one file per fetch), so the price closest to a
    kickoff survives for the closing-line value in :mod:`bet_log`; the 6h cache
    TTL only decides whether a *new* fetch is needed.
    """
    if not CACHE_DIR.exists():
        return []
    pattern = f"{event_id}__*.json" if event_id else "*__*.json"
    out: list[tuple[datetime, dict]] = []
    for path in sorted(CACHE_DIR.glob(pattern)):
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
            out.append((datetime.fromisoformat(doc["fetched_at"]), doc["data"]))
        except (ValueError, KeyError, OSError):
            continue
    out.sort(key=lambda item: item[0])
    return out


def fetch_snapshot(session, key, sport_key: str, event: dict) -> tuple[dict | None, int, str, int | None]:
    """Pinnacle h2h + totals for **one** match, via the per-event odds endpoint.

    Returns ``(data, credits, source, remaining)``; ``remaining`` is the account
    balance reported by the response that was actually made (None when cached).
    The per-event endpoint returns that match alone — the league-wide endpoint
    would return every event in the division for the same 2 credits.
    """
    data = cached(event["id"])
    if data is not None:
        return data, 0, "cache", None
    data, headers = _call(
        session, key, f"/sports/{sport_key}/events/{event['id']}/odds",
        params={"regions": REGION, "markets": ODDS_MARKETS,
                "bookmakers": BOOKMAKER, "oddsFormat": "decimal"},
        note=f"fair-sheet {event['home_team']} vs {event['away_team']}",
    )
    cost = int(float(headers.get("x-requests-last") or 0))
    if data is not None:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        (CACHE_DIR / f"{event['id']}__{stamp}.json").write_text(
            json.dumps({"fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                        "data": data}), encoding="utf-8")
    return data, cost, "api", _remaining(headers)


# --------------------------------------------------------------------------- #
# Pinnacle -> anchor
# --------------------------------------------------------------------------- #
def snapshot_events(snapshot) -> list[dict]:
    """The event objects in a snapshot, whether it is one event or a league list."""
    if isinstance(snapshot, dict):
        return [snapshot]
    return [event for event in (snapshot or []) if isinstance(event, dict)]


def pinnacle_prices(event: dict, snapshot) -> dict | None:
    """De-margined Pinnacle 1X2 + the totals line nearest 2.5, power de-margin.

    The snapshot is matched by **event id** first: the fixtures and odds feeds
    spell some clubs differently (``Bromley`` vs ``Bromley FC``), so a name-only
    match silently skips matches that do have a sharp price.
    """
    events = snapshot_events(snapshot)
    match = next((m for m in events if m.get("id") and m["id"] == event.get("id")), None)
    if match is None:
        match = next((m for m in events
                      if m.get("home_team") == event.get("home_team")
                      and m.get("away_team") == event.get("away_team")), None)
    if match is None:
        return None
    book = None
    for candidate in match.get("bookmakers", []):
        if candidate.get("key") == BOOKMAKER:
            book = candidate
    if book is None:
        return None

    tables = {m["key"]: m for m in book.get("markets", [])}
    h2h, totals = tables.get("h2h"), tables.get("totals")
    if not h2h or not totals:
        return None

    names = {o["name"]: o["price"] for o in h2h["outcomes"]}
    home, away = match.get("home_team"), match.get("away_team")
    if not {home, "Draw", away} <= set(names):
        return None
    raw_1x2 = np.array([names[home], names["Draw"], names[away]], dtype=float)
    p_1x2 = odds.demargin(pd.DataFrame([raw_1x2]), "power").to_numpy()[0]

    points: dict[float, dict[str, float]] = {}
    for outcome in totals["outcomes"]:
        points.setdefault(float(outcome["point"]), {})[outcome["name"]] = outcome["price"]
    lines = {pt: side for pt, side in points.items() if {"Over", "Under"} <= set(side)}
    if not lines:
        return None
    point = min(lines, key=lambda pt: (abs(pt - 2.5), pt))
    raw_ou = np.array([lines[point]["Over"], lines[point]["Under"]], dtype=float)
    p_ou = odds.demargin(pd.DataFrame([raw_ou]), "power").to_numpy()[0]

    return {
        "p_home": float(p_1x2[0]), "p_draw": float(p_1x2[1]), "p_away": float(p_1x2[2]),
        "p_over": float(p_ou[0]), "line": float(point),
        "raw_1x2": [float(x) for x in raw_1x2], "raw_ou": [float(x) for x in raw_ou],
        "margin_1x2": float((1.0 / raw_1x2).sum() - 1.0),
        "margin_ou": float((1.0 / raw_ou).sum() - 1.0),
        "snapshot": book.get("last_update") or h2h.get("last_update") or "",
    }


def sharp_overrides(prices: dict) -> dict[tuple[str, str], tuple[float, float]]:
    """Markets the de-margined sharp 1X2 prices **directly**, with no model between.

    Pinnacle's h2h *is* the price of a 1X2 outcome, so fitting a grid and reading
    the same outcome back off it would only add the anchor's residual error
    (typically ~2% at these margins). Double chance and the full-time
    stake-back-No-Bet prices are exact functions of the same three numbers.
    Everything else — goal ranges, per-half markets — has to come from the score
    grid anchored on the same sharp prices.
    """
    home, draw, away = prices["p_home"], prices["p_draw"], prices["p_away"]
    return {
        ("RESULT", "1"): (home, 0.0),
        ("RESULT", "X"): (draw, 0.0),
        ("RESULT", "2"): (away, 0.0),
        ("DOUBLE_CHANCE", "1X"): (home + draw, 0.0),
        ("DOUBLE_CHANCE", "12"): (home + away, 0.0),
        ("DOUBLE_CHANCE", "X2"): (draw + away, 0.0),
        ("NO_BET", "XNB FT 1"): (home, draw),
        ("NO_BET", "XNB FT 2"): (away, draw),
    }


def price_match(slug: str, prices: dict) -> tuple[list[dict], float]:
    """Fair odds for every catalogue + ext market. Returns (rows, anchor residual)."""
    from step4_pricing import league_params

    anchor = solve_anchor(prices["p_home"], prices["p_draw"], prices["p_away"],
                          prices["p_over"], line=prices["line"])
    grid = joint_grid(anchor, league_params(slug), MAX_HALF)
    probs = batch_market_probs(grids_to_flat([grid]), masks())
    status = family_status()
    sharp = sharp_overrides(prices)
    blocked = handcrafted_blocklist()

    rows = []
    for key, market in sheet_markets():
        direct = sharp.get((market.family, market.code))
        if direct is not None:
            p_win, p_void = direct
        else:
            p_win = float(probs[(market.family, market.code)][0][0])
            p_void = float(probs[(market.family, market.code)][1][0])
        odd = fair_odds(p_win, p_void)
        if not np.isfinite(odd):
            continue
        rows.append({
            "market": key,
            "code": key.split(":", 1)[1] if ":" in key else key,
            "family": market.family,
            "section": market.section,
            "meaning": meaning_of(market),
            "fair_odds": odd,
            "min_acceptable": odd * EDGE_CUSHION,
            "status": ("SHARP" if (market.family in SHARP_FAMILIES
                                    or (market.family, market.code) in SHARP_CODES)
                       else "UNTESTABLE" if not getattr(market, "testable", True)
                       else status.get(market.family, "UNTESTED")),
            "do_not_bet": key in blocked,
            "signature": settlement_signature(market.outcome),
        })
    return rows, anchor.residual


def meaning_of(market) -> str:
    """Plain-English meaning of a market, used as the sheet's middle column."""
    text = getattr(market, "definition_en", "")
    if text:
        return text
    from core.market_code import parse as parse_code

    try:
        return parse_code(market.code, market.family, section=market.section).definition_en
    except ValueError:
        return market.code


def handcrafted_blocklist() -> set[str]:
    """Codes flagged DO_NOT_BET until clarified (rules-text inconsistencies)."""
    from core.market_code import DO_NOT_BET_UNTIL_CLARIFIED

    return set(DO_NOT_BET_UNTIL_CLARIFIED)


def select(rows: list[dict]) -> tuple[list[dict], int, int]:
    """The shortlist the sheet shows. Returns (rows, hidden, suppressed).

    Kept: rows whose price is SHARP (read off the sharp price) or whose family
    PASSed calibration, minus the codes flagged DO_NOT_BET. Ordered by the family's
    typical Serbian-book margin, lowest first, then by how close the fair price is
    to even money. De-duplicated by settlement identity, then the :data:`MAX_ROWS`
    rows are **spread evenly across families** (round-robin, cheapest family
    first) so no single family fills the sheet.
    """
    candidates = [row for row in rows
                  if row["status"] in ("SHARP", "PASS") and not row["do_not_bet"]]
    hidden = len(rows) - len(candidates)
    candidates.sort(key=lambda row: (
        FAMILY_MARGIN.get(row["family"], MARGIN_UNKNOWN),
        abs(row["fair_odds"] - 2.0),
        row["market"],
    ))

    seen: set = set()
    unique: list[dict] = []
    for row in candidates:
        if row["signature"] in seen:
            continue
        seen.add(row["signature"])
        unique.append(row)

    # Group by family, preserving the margin order of first appearance, then take
    # one row from each family in turn until MAX_ROWS is reached.
    order: list[str] = []
    by_family: dict[str, list[dict]] = {}
    for row in unique:
        family = row["family"]
        if family not in by_family:
            by_family[family] = []
            order.append(family)
        by_family[family].append(row)

    kept: list[dict] = []
    cursor = {family: 0 for family in order}
    while len(kept) < MAX_ROWS:
        progressed = False
        for family in order:
            if len(kept) >= MAX_ROWS:
                break
            index = cursor[family]
            if index < len(by_family[family]):
                kept.append(by_family[family][index])
                cursor[family] = index + 1
                progressed = True
        if not progressed:
            break
    return kept, hidden, len(candidates) - len(kept)


# --------------------------------------------------------------------------- #
# Mozzart join and flags
# --------------------------------------------------------------------------- #
def mozzart_index(events: list[dict]) -> list[dict]:
    """Mozzart events with their mapped odds, ready to match to fair-sheet matches."""
    import mozzart_odds

    out = []
    for event in events:
        out.append({
            "slug": event.get("_slug"),
            "home": event.get("home"),
            "away": event.get("away"),
            "kickoff": mozzart_odds.event_kickoff(event),
            "fetched_at": event.get("_fetched_at"),
            "odds": mozzart_odds.market_odds(event),
        })
    return out


def find_mozzart(match: dict, index: list[dict]) -> dict | None:
    """The Mozzart event for a fair-sheet match, by league, names and kickoff."""
    if not match.get("kickoff"):
        return None
    kickoff = kickoff_utc(match["kickoff"])
    best, score = None, 0.0
    for entry in index:
        if entry["slug"] != match["league"] or entry["kickoff"] is None:
            continue
        if abs((entry["kickoff"] - kickoff).total_seconds()) > KICKOFF_TOLERANCE_HOURS * 3600:
            continue
        value = min(similarity(match["home"], entry["home"]),
                    similarity(match["away"], entry["away"]))
        if value >= MATCH_SIMILARITY and value > score:
            best, score = entry, value
    return best


def snapshot_gap_minutes(pinnacle_iso: str | None, mozzart_iso: str | None) -> float | None:
    """Minutes between the Pinnacle and Mozzart snapshots, or None if unknown."""
    if not pinnacle_iso or not mozzart_iso:
        return None
    try:
        left = datetime.fromisoformat(pinnacle_iso.replace("Z", "+00:00"))
        right = datetime.fromisoformat(mozzart_iso.replace("Z", "+00:00"))
    except ValueError:
        return None
    if left.tzinfo is None:
        left = left.replace(tzinfo=timezone.utc)
    if right.tzinfo is None:
        right = right.replace(tzinfo=timezone.utc)
    return abs((left - right).total_seconds()) / 60.0


def compute_flags(match: dict, mozzart: dict | None, paper: dict) -> list[dict]:
    """Rows where Mozzart beats fair x cushion on an eligible family.

    Eligible: the family PASSed calibration, or it is a SHARP main-line market
    (RESULT, DOUBLE_CHANCE, full-time No-Bet, GOAL_RANGE_FT). A row is flagged
    only when the Mozzart price is at or above ``fair x cushion``; when the two
    snapshots are more than ``max_gap_minutes`` apart the flag is marked STALE.
    """
    if mozzart is None or not match.get("rows"):
        return []
    status = family_status()
    gap = snapshot_gap_minutes(match.get("snapshot"), mozzart["fetched_at"])
    stale = gap is None or gap > paper["max_gap_minutes"]
    flags = []
    for row in match["rows"]:
        family = row["family"]
        eligible = (family in FLAG_SHARP_FAMILIES
                    or (family, row["code"]) in FLAG_SHARP_CODES
                    or status.get(family) == "PASS")
        if not eligible:
            continue
        quote = mozzart["odds"].get((family, row["code"]))
        if quote is None:
            continue
        if quote["odds"] < row["fair_odds"] * paper["edge_cushion"]:
            continue
        p_fair = 1.0 / row["fair_odds"]
        ev = (1.0 - paper["ev_haircut"]) * p_fair * quote["odds"] - 1.0
        flags.append({
            "home": match["home"], "away": match["away"], "league": match["league"],
            "kickoff": match["kickoff"], "family": family,
            "section": quote["section"], "code": quote["code"],
            "market": row["market"], "meaning": row["meaning"],
            "mozzart_odds": quote["odds"], "fair_odds": row["fair_odds"],
            "min_acceptable": row["fair_odds"] * paper["edge_cushion"],
            "ev": ev, "stale": stale, "gap_minutes": gap,
            "description": quote["description"],
            "mozzart_snapshot": mozzart["fetched_at"],
            "pinnacle_snapshot": match.get("snapshot", ""),
        })
    flags.sort(key=lambda flag: -flag["ev"])
    return flags


def append_summary(first: date, matches: list[dict], flags: list[dict], credits: int) -> None:
    """Append one line per run to reports/fair_sheets/summary.csv."""
    SUMMARY_CSV.parent.mkdir(parents=True, exist_ok=True)
    is_new = not SUMMARY_CSV.exists()
    with SUMMARY_CSV.open("a", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        if is_new:
            writer.writerow(["date", "matches", "markets_compared", "flags",
                             "requests_credits"])
        writer.writerow([first.isoformat(), len(matches),
                         sum(len(m["rows"]) for m in matches), len(flags), credits])


# --------------------------------------------------------------------------- #
# rendering
# --------------------------------------------------------------------------- #
def render(matches: list[dict], meta: dict) -> str:
    window = meta["window"]
    span = window[0] if len(window) == 1 else f"{window[0]} .. {window[-1]}"
    residual = "`anchor residual` is the RMS error of the (1X2, O/U) fit; a clean fit " \
               "is below ~0.01. Above 0.05 the sharp 1X2 and totals disagree and the " \
               "match is flagged."
    lines = [
        f"# Fair odds sheet — {span}",
        "",
        f"- **Pinnacle snapshot**: {meta['snapshot'] or 'n/a'}  ",
        f"- **Built**: {meta['built']} · sheet generated from cached/just-fetched Pinnacle prices.",
        "- **odds move — re-run within ~1h of betting.**",
        f"- **BET ONLY IF THE BOOK'S ODDS ARE >= fair x {EDGE_CUSHION}** (the value in the "
        "last column). Match the code **inside its section** — the section is what "
        "decides what a code means, so `1` is a home win under Konačni Ishod and "
        "exactly one goal under Ukupno Golova.",
        "- `SHARP` = priced off the de-margined Pinnacle price itself (RESULT, "
        "DOUBLE_CHANCE, full-time No-Bet, and the goal totals from the sharp 1X2 + "
        "totals line). `PASS` = the family's price was calibrated on unseen seasons.",
        f"- Rows are ordered by the family's typical Serbian-book margin, **lowest "
        f"first**, so the cheapest sections come first; the {MAX_ROWS} rows are "
        f"spread evenly across families so no one family fills the sheet.",
        f"- {residual}",
        f"- Leagues: {meta['leagues'] or 'n/a'} · matches: {meta['matches']} · "
        f"credits this run: {meta['credits']} · remaining: {meta['remaining']}",
        "",
    ]
    if meta["notes"]:
        lines += [f"> {note}" for note in meta["notes"]] + [""]

    flags = meta.get("flags", [])
    lines += ["## FLAGS", ""]
    if not flags:
        lines += ["No value today.", ""]
    else:
        lines += [
            "| match | kickoff | section | code | meaning | Mozzart | min | EV (20% haircut) |",
            "|---|---|---|---|---|---:|---:|---:|",
        ]
        for flag in flags:
            tag = " ⚠ STALE" if flag["stale"] else ""
            lines.append(
                f"| {flag['home']} vs {flag['away']} | {flag['kickoff']} "
                f"| {flag['section']} | `{flag['code']}` | {flag['meaning']} "
                f"| {flag['mozzart_odds']:.2f} | {flag['min_acceptable']:.2f} "
                f"| {flag['ev']:+.1%}{tag} |")
        lines.append("")

    for match in matches:
        head = f"## {match['home']} vs {match['away']} — {match['league']}"
        if match["error"]:
            lines += ["", head, f"_{match['error']}_", ""]
            continue
        resid = match.get("residual", 0.0)
        warn = " ⚠ Pinnacle 1X2 and totals disagree — treat with care" if resid > 0.05 else ""
        lines += [
            "",
            head,
            f"`{match['kickoff']}` · Pinnacle snapshot `{match['snapshot']}` · "
            f"1X2 margin {match['margin_1x2']:+.3%} (Pinnacle "
            f"{'/'.join(f'{p:.2f}' for p in match['raw_1x2'])}) · "
            f"totals {match['line']:g} margin {match['margin_ou']:+.3%} · "
            f"anchor residual {resid:.4f}{warn}",
            "",
        ]
        if not match["rows"]:
            lines += ["_no market in a shown family_", ""]
            continue
        eligible = len(match["rows"]) + match["suppressed"]
        lines += [
            f"_{len(match['rows'])} of {eligible} eligible prices shown; "
            f"{match['hidden']} hidden; {match['suppressed']} below the cut_",
            "",
            "| section | code | meaning | fair | bet if ≥ |",
            "|---|---|---|---:|---:|",
        ]
        for row in match["rows"]:
            lines.append(
                f"| {row['section']} | `{row['market']}` | {row['meaning']} "
                f"| {row['fair_odds']:.2f} | **{row['min_acceptable']:.2f}** |"
            )
        lines.append("")

    lines += [
        "---",
        "",
        "`SHARP` rows come straight off the sharp price; `PASS` families were "
        "calibrated on unseen seasons. A row whose fair price and the book's price "
        "agree is not a bet — only a price at or above the last column is.",
        "",
        "Two codes that settle identically on every scoreline are shown once.",
    ]
    return "\n".join(lines) + "\n"


CSV_FIELDS = ["date", "kickoff_local", "league", "home", "away", "section", "market",
              "family", "meaning", "fair_odds", "min_acceptable_odds", "status",
              "pinnacle_snapshot"]


def write_csv(path: Path, matches: list[dict]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for match in matches:
            for row in match["rows"]:
                writer.writerow({
                    "date": match["date"], "kickoff_local": match["kickoff"],
                    "league": match["league"], "home": match["home"], "away": match["away"],
                    "section": row["section"], "market": row["market"],
                    "family": row["family"], "meaning": row["meaning"],
                    "fair_odds": f"{row['fair_odds']:.4f}",
                    "min_acceptable_odds": f"{row['min_acceptable']:.4f}",
                    "status": row["status"], "pinnacle_snapshot": match["snapshot"],
                })
                n += 1
    return n


# --------------------------------------------------------------------------- #
# entry point
# --------------------------------------------------------------------------- #
def main(start: str | None = None, days: int = 1) -> int:
    first = date.fromisoformat(start) if start else date.today()
    window = {first + timedelta(days=offset) for offset in range(max(days, 1))}

    key = load_key()
    session = requests.Session()
    events, headers, started = upcoming_events(session, key, window)
    remaining = _remaining(headers)
    built = datetime.now().astimezone().isoformat(timespec="minutes")
    notes: list[str] = []

    paper = load_paper_config()
    mozzart: list[dict] = []
    try:
        import mozzart_odds

        mkey = mozzart_odds.load_key()
        ids = mozzart_odds.league_ids(session, mkey)
        raw_events = mozzart_odds.fetch_events(session, mkey, ids)
        mozzart = mozzart_index(raw_events)
        notes.append(f"Mozzart: {len(raw_events)} event(s) across {len(ids)} league(s) "
                     f"({', '.join(sorted(ids)) or 'none mapped'}).")
    except Exception as exc:  # noqa: BLE001
        notes.append(f"Mozzart feed unavailable ({exc}); no flags this run.")

    print(f"fair-sheet {first} (+{max(days, 1) - 1}d): {len(events)} upcoming matches in window"
          + (f", {started} already started (skipped)" if started else ""))
    print(f"credits remaining before pull: {remaining}")

    matches: list[dict] = []
    credits = 0
    cached_hits = 0
    pinned: str | None = None
    stopped: str | None = None

    for sport_key, event in events:
        slug = SPORTS[sport_key]
        record = {
            "date": local_date(event["commence_time"]).isoformat(),
            "kickoff": event["commence_time"], "league": slug,
            "home": event["home_team"], "away": event["away_team"],
            "rows": [], "hidden": 0, "suppressed": 0, "error": "",
        }
        if stopped is None:
            snapshot, cost, source, balance = fetch_snapshot(session, key, sport_key, event)
            credits += cost
            cached_hits += source == "cache"
            if balance is not None:
                remaining = balance
            prices = pinnacle_prices(event, snapshot) if snapshot else None
            if prices is None:
                record["error"] = ("no Pinnacle h2h + totals in the snapshot "
                                   f"({source}) — match skipped")
                record["snapshot"] = ""
            else:
                try:
                    rows, residual = price_match(slug, prices)
                except Exception as exc:  # noqa: BLE001
                    record["error"] = f"could not price: {exc}"
                    rows = []
                kept, hidden, suppressed = select(rows)
                record.update({
                    "rows": kept, "hidden": hidden, "suppressed": suppressed,
                    "snapshot": prices["snapshot"] or "n/a",
                    "raw_1x2": prices["raw_1x2"], "line": prices["line"],
                    "margin_1x2": prices["margin_1x2"], "margin_ou": prices["margin_ou"],
                    "residual": residual,
                })
                record["flags"] = compute_flags(record, find_mozzart(record, mozzart), paper)
                pinned = pinned or prices["snapshot"]
        else:
            record["error"] = f"not fetched: {stopped}"
            record["snapshot"] = ""
        matches.append(record)

        spent_fraction = credits >= CREDIT_CAP
        if stopped is None and (spent_fraction or (remaining is not None and remaining < MIN_REMAINING)):
            stopped = (f"credit cap {CREDIT_CAP} reached" if spent_fraction
                       else f"account below {MIN_REMAINING} credits ({remaining})")
            notes.append(f"Stopped after {credits} credits: {stopped}. Later matches "
                         "were not fetched.")

    if cached_hits:
        notes.append(f"{cached_hits} match(es) served from the {CACHE_HOURS}h cache (0 credits).")
    if started:
        notes.append(f"{started} match(es) in the window had already kicked off and were "
                     "skipped (no credits spent).")

    all_flags = [flag for match in matches for flag in match.get("flags", [])]
    meta = {
        "window": sorted(window), "built": built, "snapshot": pinned,
        "leagues": ", ".join(sorted({m["league"] for m in matches})),
        "matches": len(matches), "credits": credits,
        "remaining": remaining, "notes": notes, "flags": all_flags,
    }
    text = render(matches, meta)
    stem = first.isoformat() if days <= 1 else f"{first.isoformat()}_{max(days, 1)}d"
    SHEET_DIR.mkdir(parents=True, exist_ok=True)
    md_path = SHEET_DIR / f"{stem}.md"
    csv_path = SHEET_DIR / f"{stem}.csv"
    md_path.write_text(text, encoding="utf-8")
    n_rows = write_csv(csv_path, matches)
    append_summary(first, matches, all_flags, credits)
    if all_flags:
        import paper_trade

        added = paper_trade.record(all_flags)
        print(f"paper bets recorded: {added} (of {len(all_flags)} flags)")

    shown = sum(1 for m in matches if m["rows"])
    print(f"matches priced: {shown}/{len(matches)} · rows written: {n_rows} · "
          f"flags: {len(all_flags)}")
    print(f"credits this run: {credits} (cap {CREDIT_CAP}) · remaining {remaining} "
          f"· cached {cached_hits}")
    print(f"wrote {md_path}")
    print(f"wrote {csv_path}")
    for note in notes:
        print(f"  note: {note}")
    odds_api_log.print_today()
    return 0


if __name__ == "__main__":
    sys.argv = [sys.argv[0]]
    sys.exit(main())