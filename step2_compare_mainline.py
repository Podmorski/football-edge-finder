"""Step 2 — compare Soccer Bet's main line against sharp prices.

Sharp prices (Pinnacle, region eu) are used ONLY as the reference for true
probability. Bets would be placed ONLY at Soccer Bet, only in the lowest-margin
market capturing the deviation, and never combos.

For each match:
  * de-margin the sharp 1X2 (power method; proportional as sensitivity)
  * for 1X2, DC, X No Bet and every goal-total line Soccer Bet offers, report
    p_sharp, Soccer Bet odds and EV = p_sharp * odds - 1
  * price EVERY Soccer Bet market with the half model anchored on the sharp
    1X2 + O/U 2.5, and report the cheapest Soccer Bet representation
  * output the max-EV market and flag only if EV > +3% after a safety haircut
    (p_sharp shrunk 20% toward Soccer Bet's de-margined probability)
  * flag STALE unless the sharp snapshot is within 60 minutes of the capture
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from core import odds as odds_mod
from core.half_model import (
    Anchor,
    batch_market_probs,
    fair_odds,
    grids_to_flat,
    joint_grid,
    market_masks,
    solve_anchor,
)
from core.market_code import direct_markets, parse

SNAP = Path("data/odds_snapshots/oddsapi")
HAIRCUT = 0.20          # shrink p_sharp 20% toward Soccer Bet's de-margined p
FLAG_THRESHOLD = 0.03   # flag only if EV > +3% after the haircut
STALE_MINUTES = 60
MAX_HALF = 6

SPORT_BY_LEAGUE = {
    "bundesliga_1": "soccer_germany_bundesliga",
    "bundesliga_2": "soccer_germany_bundesliga2",
    "league_one": "soccer_england_league1",
    "league_one_t3": "soccer_england_league1",
    "ligue_2": "soccer_france_ligue_two",
    "ligue_2_t2": "soccer_france_ligue_two",
}

DIRECT_FAMILIES = {
    "WIN_BOTH_HALVES", "WIN_TO_NIL", "MARGIN", "NO_BET",
    "MORE_GOALS_HALF", "FIRST_GOAL", "TO_QUALIFY",
}


def demargin_power(odds: np.ndarray) -> np.ndarray:
    raw = 1.0 / np.asarray(odds, dtype=float)
    lo, hi = 0.5, 5.0
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        if np.power(raw, mid).sum() > 1.0:
            lo = mid
        else:
            hi = mid
    p = np.power(raw, 0.5 * (lo + hi))
    return p / p.sum()


def demargin_proportional(odds: np.ndarray) -> np.ndarray:
    raw = 1.0 / np.asarray(odds, dtype=float)
    return raw / raw.sum()


def find_sharp(league: str, home: str, away: str) -> tuple[dict | None, str]:
    """Locate the saved sharp snapshot for a match. Returns (payload, source)."""
    sport = SPORT_BY_LEAGUE.get(league)
    if sport is None:
        return None, "unknown league"
    for path in sorted(SNAP.glob(f"*_{sport}_*_h2h_totals.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        for event in data:
            if home.lower() in event["home_team"].lower() and away.lower() in event["away_team"].lower():
                return event, path.name
    return None, "no saved snapshot"


def sharp_probs(event: dict) -> tuple[np.ndarray, np.ndarray, str]:
    """De-margined sharp 1X2 and O/U 2.5, preferring Pinnacle."""
    books = event.get("bookmakers", [])
    pin = [b for b in books if b["key"] == "pinnacle"]
    source = "pinnacle"
    if not pin:
        pin = books
        source = "median_eu"
    h2h = None
    totals = None
    for b in pin:
        for m in b.get("markets", []):
            if m["key"] == "h2h" and h2h is None:
                h2h = m
            if m["key"] == "totals" and totals is None:
                totals = m
    if h2h is None:
        return np.array([]), np.array([]), "no h2h"

    names = {o["name"]: o["price"] for o in h2h["outcomes"]}
    home_odds = next(v for k, v in names.items() if k.lower() in event["home_team"].lower())
    away_odds = next(v for k, v in names.items() if k.lower() in event["away_team"].lower())
    draw_odds = next(v for k, v in names.items() if k.lower() == "draw")
    p1 = demargin_power(np.array([home_odds, draw_odds, away_odds]))

    p_ou = np.array([np.nan, np.nan])
    if totals is not None:
        over = next((o["price"] for o in totals["outcomes"]
                     if o["name"].lower() == "over" and abs(o.get("point", 0) - 2.5) < 1e-9), None)
        under = next((o["price"] for o in totals["outcomes"]
                      if o["name"].lower() == "under" and abs(o.get("point", 0) - 2.5) < 1e-9), None)
        if over and under:
            p_ou = demargin_power(np.array([over, under]))
    return p1, p_ou, source


def snapshot_time(name: str) -> datetime | None:
    """Parse the UTC fetch time embedded in a snapshot filename."""
    try:
        stamp = name.split("_", 1)[0]
        return datetime.strptime(stamp, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
    except Exception:
        return None


def main(csv_path: str) -> int:
    frame = pd.read_csv(csv_path)
    frame["code"] = frame["code"].astype(str)
    print("=" * 100)
    print(f"compare-mainline: {csv_path}  ({len(frame)} rows)")
    print("=" * 100)

    for (league, home, away), group in frame.groupby(["league", "home", "away"]):
        print(f"\n--- {league}: {home} vs {away} ---")
        event, src = find_sharp(league, home, away)
        if event is None:
            print(f"  no sharp snapshot ({src}) - cannot compare")
            continue
        p1, p_ou, book = sharp_probs(event)
        if p1.size == 0:
            print(f"  sharp h2h unavailable ({book})")
            continue

        capture = pd.to_datetime(group["capture_time_local"].iloc[0], errors="coerce")
        fetched = snapshot_time(src)
        stale = True
        gap_min = None
        if pd.notna(capture) and fetched is not None:
            capture_utc = capture.tz_localize("UTC") if capture.tzinfo is None else capture.tz_convert("UTC")
            gap_min = abs((fetched - capture_utc).total_seconds()) / 60.0
            stale = gap_min > STALE_MINUTES
        print(f"  sharp source: {book} | snapshot {src}")
        print(f"  sharp 1X2 (power de-margin): home {p1[0]:.4f} draw {p1[1]:.4f} away {p1[2]:.4f}")
        if np.isfinite(p_ou).all():
            print(f"  sharp O/U 2.5: over {p_ou[0]:.4f} under {p_ou[1]:.4f}")
        if gap_min is None:
            print(f"  capture {capture} vs sharp snapshot {fetched} -> STALE (timestamp unreadable)")
        else:
            print(f"  capture {capture} vs sharp snapshot {fetched} "
                  f"({gap_min:.0f} min apart) -> {'STALE' if stale else 'within 60 min'}")

        # --- EV on the main line, anchored on the sharp de-margined probabilities
        print(f"\n  {'market':<10}{'code':<12}{'sb odds':>9}{'p_sharp':>10}{'EV':>9}"
              f"{'EV after haircut':>18}{'flag':>7}")
        rows = []
        for r in group.itertuples(index=False):
            code = r.code
            p_sharp = None
            if r.market == "1X2":
                p_sharp = {"1": p1[0], "X": p1[1], "2": p1[2]}.get(code)
            elif r.market == "DC":
                p_sharp = {"1X": p1[0] + p1[1], "12": p1[0] + p1[2], "X2": p1[1] + p1[2]}.get(code)
            elif r.market == "XNB" and np.isfinite(p_ou).all():
                side = 1 if code.endswith("1") else 2
                p_win = p1[0] if side == 1 else p1[2]
                p_sharp = p_win / (1 - p1[1]) if p1[1] < 1 else None
            elif r.market == "goals":
                p_sharp = None  # needs the sharp totals distribution; see the model block
            if p_sharp is None:
                continue
            ev = p_sharp * float(r.odds) - 1.0
            # safety haircut: shrink p_sharp toward Soccer Bet's de-margined p
            sb_p = (1.0 / float(r.odds))
            p_hair = p_sharp * (1 - HAIRCUT) + sb_p * HAIRCUT
            ev_hair = p_hair * float(r.odds) - 1.0
            flag = ev_hair > FLAG_THRESHOLD
            rows.append((r.market, code, float(r.odds), p_sharp, ev, ev_hair, flag))
            print(f"  {r.market:<10}{code:<12}{float(r.odds):>9.3f}{p_sharp:>10.4f}"
                  f"{ev:>9.4f}{ev_hair:>18.4f}{str(flag):>7}")

        # --- sharp-anchored fair price of every Soccer Bet market
        if np.isfinite(p_ou).all():
            anchor = solve_anchor(p1[0], p1[1], p1[2], p_ou[0])
            catalogue = []
            direct = {m.code: m for m in direct_markets()}
            import yaml

            for entry in yaml.safe_load(Path("config/markets_catalogue.yaml").read_text(encoding="utf-8"))["markets"]:
                catalogue.append(direct[entry["code"]] if entry["family"] in DIRECT_FAMILIES
                                 else parse(entry["code"], entry["family"]))
            masks = market_masks(catalogue, MAX_HALF)
            grid = joint_grid(anchor, None, MAX_HALF)
            probs = batch_market_probs(grids_to_flat([grid]), masks)
            print(f"\n  sharp-anchored fair prices (anchor lam={anchor.lam:.3f} mu={anchor.mu:.3f}):")
            for r in group.itertuples(index=False):
                key = None
                for m in catalogue:
                    if m.code == r.code:
                        key = (m.family, m.code)
                        break
                if key is None or key not in probs:
                    continue
                p_win, p_void = probs[key][0][0], probs[key][1][0]
                fo = fair_odds(p_win, p_void)
                ev = p_win * float(r.odds) - 1.0
                print(f"    {r.market:<8}{r.code:<12} fair {fo:>7.3f}  sb {float(r.odds):>6.3f}  EV {ev:+.4f}")

        if rows:
            best = max(rows, key=lambda x: x[5])
            print(f"\n  MAX EV after haircut: {best[0]} {best[1]} at {best[2]:.3f} -> "
                  f"EV {best[5]:+.4f} {'FLAGGED' if best[6] else '(not flagged)'}")
        else:
            print("\n  no comparable main-line rows")

    print("\nNOTE: sharp prices are the probability reference only. Bets would be placed")
    print("      only at Soccer Bet, only in the lowest-margin market capturing the")
    print("      deviation, and never combos. No ROI is claimed.")
    print("      PLACEHOLDER Soccer Bet odds give meaningless EVs - this run is a")
    print("      PIPELINE TEST only, not a result.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "templates/soccerbet_mainline.csv"))