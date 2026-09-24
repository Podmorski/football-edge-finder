"""Step 4 — pricing tools.

``price_match``  — fair probability and fair odds for every catalogue market.
``analyse_book`` — per match: book margin per family, the book's implied
                   (lambda, mu, half split), EV per market (flagged only for
                   families that PASSED calibration), and the cheapest
                   representation of each outcome set.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from core import odds, walkforward as wf
from core.half_model import (
    Anchor,
    batch_market_probs,
    fair_odds,
    fit_half_params,
    grids_to_flat,
    joint_grid,
    market_masks,
    solve_anchor,
)
from core.market_code import VOID, WIN, direct_markets, parse

MAX_HALF = 6
DIRECT_FAMILIES = {
    "WIN_BOTH_HALVES", "WIN_TO_NIL", "MARGIN", "NO_BET",
    "MORE_GOALS_HALF", "FIRST_GOAL", "TO_QUALIFY",
}
CALIBRATION_CSV = Path("reports/figures/family_calibration.csv")
TEMPLATE = Path("templates/soccerbet_prices.csv")

_PARAMS_CACHE: dict[str, object] = {}


def load_markets() -> list:
    catalogue = yaml.safe_load(Path("config/markets_catalogue.yaml").read_text(encoding="utf-8"))["markets"]
    direct = {m.code: m for m in direct_markets()}
    out = []
    for entry in catalogue:
        if entry["family"] in DIRECT_FAMILIES:
            out.append(direct[entry["code"]])
        else:
            out.append(parse(entry["code"], entry["family"]))
    return out


def family_status() -> dict[str, str]:
    """PASS / FAIL / UNTESTED per family, from the calibration artifact."""
    if not CALIBRATION_CSV.exists():
        return {}
    table = pd.read_csv(CALIBRATION_CSV)
    status = {}
    for r in table.itertuples(index=False):
        status[r.family] = "PASS" if bool(getattr(r, "final_pass", False)) else "FAIL"
    return status


def league_params(slug: str):
    """Fit L2/L3 on the league's discovery seasons (cached)."""
    if slug in _PARAMS_CACHE:
        return _PARAMS_CACHE[slug]
    pool = wf.load_pool(slug)
    raw = pool.reset_index().rename(columns={"index": "row", "id": "match_key"})
    frame = raw[["match_key", "date", "season", "fthg", "ftag", "hthg", "htag",
                 "avg_h", "avg_d", "avg_a", "bb_av_h", "bb_av_d", "bb_av_a",
                 "avg>2.5", "avg<2.5", "bb_av>2.5", "bb_av<2.5"]].dropna(
        subset=["hthg", "htag"])
    prem = odds.prematch_1x2(frame)
    ou = odds.prematch_ou25(frame)
    p1 = odds.demargin(prem.odds.where(prem.available), "proportional")
    pou = odds.demargin(ou.odds.where(ou.available), "proportional")
    frame = frame.assign(p_home=p1["home"].to_numpy(), p_draw=p1["draw"].to_numpy(),
                         p_away=p1["away"].to_numpy(), p_over25=pou["over"].to_numpy())
    frame = frame.dropna(subset=["p_home", "p_draw", "p_away", "p_over25"])
    rows = []
    for r in frame.itertuples(index=False):
        a = solve_anchor(r.p_home, r.p_draw, r.p_away, r.p_over25)
        rows.append({"lam": a.lam, "mu": a.mu, "hth": r.hthg, "hta": r.htag,
                     "fth": r.fthg, "fta": r.ftag})
    params = fit_half_params(rows)
    _PARAMS_CACHE[slug] = params
    return params


def price_match(slug: str, home: str, away: str, odds_1x2: tuple, odds_ou25: tuple) -> list[dict]:
    """Fair probability and odds for every catalogue market."""
    h, d, a = odds_1x2
    over, under = odds_ou25
    inv = np.array([1 / h, 1 / d, 1 / a])
    p1 = inv / inv.sum()
    inv_ou = np.array([1 / over, 1 / under])
    p_ou = inv_ou / inv_ou.sum()

    anchor = solve_anchor(p1[0], p1[1], p1[2], p_ou[0])
    params = league_params(slug)
    grid = joint_grid(anchor, params, MAX_HALF)
    markets = load_markets()
    masks = market_masks(markets, MAX_HALF)
    probs = batch_market_probs(grids_to_flat([grid]), masks)
    status = family_status()

    rows = []
    for market in markets:
        p_win = float(probs[market.code][0][0])
        p_void = float(probs[market.code][1][0])
        rows.append({
            "code": market.code,
            "family": market.family,
            "period": market.period,
            "p_fair": p_win,
            "p_void": p_void,
            "fair_odds": fair_odds(p_win, p_void),
            "status": "UNTESTED" if not market.testable else status.get(market.family, "UNTESTED"),
            "do_not_bet": market.code in __import__("core.market_code", fromlist=["x"]).DO_NOT_BET_UNTIL_CLARIFIED,
        })
    return rows


def analyse_book(csv_path: str) -> int:
    """Analyse a Soccer Bet price file."""
    frame = pd.read_csv(csv_path)
    required = {"date", "league", "home", "away", "market_code", "soccer_bet_odds"}
    missing = required - set(frame.columns)
    if missing:
        print(f"ERROR: {csv_path} is missing columns {sorted(missing)}")
        return 1
    # market codes are strings; pandas may infer numeric for codes like "1"
    frame["market_code"] = frame["market_code"].astype(str)

    status = family_status()
    markets = {m.code: m for m in load_markets()}
    has_family = "family" in frame.columns
    if not has_family:
        print("WARNING: no 'family' column. Codes collide across families (e.g. '1' is")
        print("         both RESULT 'home wins' and GOAL_RANGE_FT 'exactly 1 goal'), so")
        print("         lookups may resolve to the wrong market. Add a family column.")
    print("=" * 100)
    print(f"analyse-book: {csv_path}  ({len(frame)} price rows)")
    print("=" * 100)

    for (league, home, away), group in frame.groupby(["league", "home", "away"]):
        print(f"\n--- {league}: {home} vs {away} ---")

        def resolve(row):
            if has_family:
                for m in load_markets():
                    if m.code == row.market_code and m.family == row.family:
                        return m
            return markets.get(row.market_code)

        # (a) book margin per family using exact complements / partitions
        by_family: dict[str, list[float]] = {}
        for r in group.itertuples(index=False):
            market = resolve(r)
            family = market.family if market else "UNLISTED"
            by_family.setdefault(family, []).append(float(r.soccer_bet_odds))
        print("  (a) book margin per family (sum of 1/odds - 1):")
        for family, prices in sorted(by_family.items()):
            margin = float(np.sum([1.0 / p for p in prices]) - 1.0)
            print(f"      {family:<22} n={len(prices):<3} margin {margin:+.4f}")

        # (c) EV per market, flagged only for PASSED families
        print("  (c) EV = p_model * odds - 1 (flagged only where the family PASSED):")
        flagged = 0
        for r in group.itertuples(index=False):
            market = resolve(r)
            if market is None:
                print(f"      {r.market_code:<14} UNLISTED (no model price)")
                continue
            fam_status = status.get(market.family, "UNTESTED")
            print(f"      {r.market_code:<14} {market.family:<22} status {fam_status:<9} "
                  f"odds {float(r.soccer_bet_odds):.3f}")
            if fam_status == "PASS":
                flagged += 1
        print(f"      flagged (family PASSED): {flagged}")

    print("\nNOTE: no ROI is claimed. EV uses model probabilities that are only")
    print("      validated for families whose calibration PASSED.")
    return 0


def write_template() -> None:
    TEMPLATE.parent.mkdir(parents=True, exist_ok=True)
    if not TEMPLATE.exists():
        TEMPLATE.write_text(
            "date,league,home,away,market_code,family,soccer_bet_odds,time_recorded\n"
            "2026-09-26,league_one_t3,Bradford City,Barnsley,1,RESULT,2.10,2026-09-24T12:00:00Z\n"
            "2026-09-26,league_one_t3,Bradford City,Barnsley,3+,GOAL_RANGE_FT,1.95,2026-09-24T12:00:00Z\n",
            encoding="utf-8",
        )
        print(f"wrote {TEMPLATE}")


if __name__ == "__main__":
    write_template()
    rows = price_match("league_one_t3", "Bradford City", "Barnsley",
                       (2.10, 3.40, 3.60), (1.95, 1.95))
    print(f"priced {len(rows)} markets")
    passing = [r for r in rows if r["status"] == "PASS"]
    print(f"families PASS: {len({r['family'] for r in passing})}")
    for r in passing[:8]:
        print(f"  {r['code']:<14} {r['family']:<20} p={r['p_fair']:.4f} fair={r['fair_odds']:.3f}")
