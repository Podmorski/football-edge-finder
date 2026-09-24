"""Step 1c — analyse-book on the Soccer Bet sample, with dual anchoring.

Prices every Soccer Bet market through the half model, twice:

(i)  anchored on Soccer Bet's **own** de-margined main line (1X2 from FT:1/X/2,
     O/U 2.5 from T:0-2 / T:3+);
(ii) anchored on the saved **Pinnacle** snapshot — flagged STALE when it is more
     than 60 minutes from the capture time.

The book's own margin makes (i) the honest "is the book self-consistent?" view:
with the book's structure correct, (i) should show ≈ 0 positive-EV markets. (ii)
adds the sharp market's information, so any positive EV there is the actual
MAINLINE-1 question — but only where the snapshot is fresh and the family's
calibration PASSED.

Reports: margin per family, implied 1H goal share, positive-EV counts under both
anchors, the top 15 markets by EV under (ii), and EV per 1X2 outcome.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import minimize_scalar
from scipy.stats import poisson

from core.half_model import Anchor, joint_grid, solve_anchor
from core.soccerbet_ext import VOID, WIN, resolve
from step1b_ingest_soccerbet import (
    MATCH,
    OUT as SB_CSV,
    margin_table,
    parse_blocks,
    print_margin_table,
)
from step4_pricing import family_status, league_params

MAX_HALF = 6
SNAP_DIR = Path("data/odds_snapshots/oddsapi")
EV_CSV = Path("data/soccerbet/2026-09-24_ev_table.csv")
STALE_MINUTES = 60
HAIRCUT = 0.20
CAPTURE_UTC_OFFSET_HOURS = 2  # Europe/Belgrade in September (CEST = UTC+2)


# --------------------------------------------------------------------------- #
# odds helpers
# --------------------------------------------------------------------------- #
def demargin_power(odds: list[float]) -> np.ndarray:
    """Power-method de-margin: find k with sum((1/odds)^k) = 1, normalise."""
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


def poisson_mean_from_tail(p_tail: float, k: int = 2) -> float:
    """Solve for the Poisson mean whose P(X > k) equals p_tail."""
    lo, hi = 1e-3, 20.0
    for _ in range(100):
        mid = 0.5 * (lo + hi)
        if poisson.sf(k, mid) > p_tail:
            hi = mid
        else:
            lo = mid
    return 0.5 * (lo + hi)


def poisson_mean_from_buckets(probs: list[float], open_at: int) -> float:
    """Least-squares Poisson mean fitted to P(0)..P(open_at)+ bucket masses."""
    def err(m: float) -> float:
        model = [float(poisson.pmf(k, m)) for k in range(open_at)] + [float(poisson.sf(open_at - 1, m))]
        return sum((model[i] - probs[i]) ** 2 for i in range(len(probs)))

    res = minimize_scalar(err, bounds=(0.05, 10.0), method="bounded")
    return float(res.x)


def price_grid(grid: np.ndarray, market) -> tuple[float, float]:
    """(p_win, p_void) for an ExtMarket under the joint grid."""
    n = grid.shape[0]
    win = void = 0.0
    for h1 in range(n):
        for a1 in range(n):
            for h2 in range(n):
                for a2 in range(n):
                    p = grid[h1, a1, h2, a2]
                    if p <= 0:
                        continue
                    out = market.outcome(h1, a1, h1 + h2, a1 + a2)
                    if out == WIN:
                        win += p
                    elif out == VOID:
                        void += p
    return float(win), float(void)


# --------------------------------------------------------------------------- #
# Pinnacle snapshot
# --------------------------------------------------------------------------- #
def _market(book: dict, key: str) -> dict | None:
    return next((m for m in book.get("markets", []) if m["key"] == key), None)


def _median_odds(books: list[dict], market_key: str) -> dict[tuple[str, float | None], float]:
    """Median price per (name, point) across books — fallback reference."""
    per: dict[tuple[str, float | None], list[float]] = {}
    for b in books:
        m = _market(b, market_key)
        if not m:
            continue
        for o in m["outcomes"]:
            per.setdefault((o["name"], o.get("point")), []).append(float(o["price"]))
    return {k: float(np.median(v)) for k, v in per.items()}


def find_pinnacle_event() -> tuple[dict | None, str]:
    for path in sorted(SNAP_DIR.glob("*_soccer_germany_bundesliga_*_h2h_totals.json")):
        for event in json.loads(path.read_text(encoding="utf-8")):
            if MATCH["home"].split()[-1].lower() in event.get("home_team", "").lower():
                return event, path.name
    return None, "not found"


def pinnacle_main(payload: dict) -> tuple[np.ndarray, np.ndarray, str, float, np.ndarray]:
    """(p_1X2, p_over_under, source, line, odds_1X2) from the snapshot."""
    books = payload.get("bookmakers", [])
    pin = next((b for b in books if b["key"] == "pinnacle"), None)
    source = "pinnacle" if pin else "median_eu"

    if pin:
        h2h = {o["name"]: float(o["price"]) for o in _market(pin, "h2h")["outcomes"]}
        totals = {(o["name"], o.get("point")): float(o["price"])
                  for o in _market(pin, "totals")["outcomes"]}
    else:
        h2h = {name: price for (name, _pt), price in _median_odds(books, "h2h").items()}
        totals = _median_odds(books, "totals")

    home = next(v for k, v in h2h.items() if MATCH["home"].split()[-1].lower() in k.lower())
    away = next(v for k, v in h2h.items() if "hamburger" in k.lower())
    draw = h2h["Draw"]
    p1 = demargin_power([home, draw, away])

    over_name = next(k for k in totals if k[0].lower() == "over")
    under_name = next(k for k in totals if k[0].lower() == "under")
    over, line = totals[over_name], float(over_name[1] or 2.5)
    under = totals[under_name]
    p_ou = demargin_power([over, under])
    return p1, p_ou, source, line, np.array([home, draw, away])


# --------------------------------------------------------------------------- #
def implied_1h_share(sb: dict[tuple[str, str], float]) -> float | None:
    """Soccer Bet's own E[1H goals] / E[FT goals], from its T1 and T: prices."""
    t1 = ["T1:0", "T1:1", "T1:2", "T1:3", "T1:4+"]
    if not all(k in sb for k in t1):
        return None
    probs = demargin_power([sb[k] for k in t1])
    mean_1h = poisson_mean_from_buckets(list(probs), open_at=4)
    p_over = demargin_power([sb["T:3+"], sb["T:0-2"]])[0]
    mean_ft = poisson_mean_from_tail(float(p_over), k=2)
    return mean_1h / mean_ft if mean_ft > 0 else None


def main() -> int:
    print("=" * 100)
    print(f"Step 1c — analyse-book: {MATCH['home']} vs {MATCH['away']} "
          f"({MATCH['league']}, kickoff {MATCH['date']})")
    print("=" * 100)

    rows = parse_blocks()
    sb = {f"{p}:{c}": o for p, c, o in rows}

    # --- (i) Soccer Bet's OWN de-margined main line -----------------------
    p1_sb = demargin_power([sb["FT:1"], sb["FT:X"], sb["FT:2"]])
    p_ou_sb = demargin_power([sb["T:3+"], sb["T:0-2"]])
    print("\n(i) Soccer Bet's own de-margined main line")
    print(f"    odds  : home {sb['FT:1']:.2f} draw {sb['FT:X']:.2f} away {sb['FT:2']:.2f}"
          f"   | over2.5 {sb['T:3+']:.2f} under2.5 {sb['T:0-2']:.2f}")
    print(f"    1X2   : home {p1_sb[0]:.4f} draw {p1_sb[1]:.4f} away {p1_sb[2]:.4f}")
    print(f"    O/U2.5: over {p_ou_sb[0]:.4f} under {p_ou_sb[1]:.4f}"
          f"   (margin {1/sb['FT:1']+1/sb['FT:X']+1/sb['FT:2']-1:+.4f})")

    share = implied_1h_share(sb)
    print(f"    implied 1H goal share: {share:.4f}" if share else "    implied 1H share: n/a")

    params = league_params(MATCH["league"])
    anchor_sb = solve_anchor(p1_sb[0], p1_sb[1], p1_sb[2], float(p_ou_sb[0]))
    grid_sb = joint_grid(anchor_sb, params, MAX_HALF)
    model_share = params.first_half_share(anchor_sb.lam, anchor_sb.mu)
    print(f"    anchor: lam {anchor_sb.lam:.3f} mu {anchor_sb.mu:.3f} "
          f"residual {anchor_sb.residual:.5f} | model 1H share {model_share:.4f}")

    # --- (ii) Pinnacle snapshot ------------------------------------------
    payload, snap_name = find_pinnacle_event()
    capture = datetime.fromisoformat(MATCH["capture_time_local"]).replace(
        tzinfo=timezone.utc) - pd.Timedelta(hours=CAPTURE_UTC_OFFSET_HOURS)
    grid_pin = None
    if payload:
        p1_pin, p_ou_pin, source, line, odds_pin = pinnacle_main(payload)
        fetched = datetime.strptime(snap_name.split("_", 1)[0], "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
        gap = abs((fetched - capture).total_seconds()) / 60.0
        stale = gap > STALE_MINUTES
        print(f"\n(ii) Pinnacle snapshot: {snap_name}")
        print(f"     odds  : home {odds_pin[0]:.2f} draw {odds_pin[1]:.2f} away {odds_pin[2]:.2f}"
              f"   (source {source})")
        print(f"     1X2   : home {p1_pin[0]:.4f} draw {p1_pin[1]:.4f} away {p1_pin[2]:.4f}")
        print(f"     O/U {line}: over {p_ou_pin[0]:.4f} under {p_ou_pin[1]:.4f}")
        print(f"     capture {capture:%Y-%m-%d %H:%M}Z vs snapshot {fetched:%Y-%m-%d %H:%M}Z "
              f"({gap:.0f} min apart) -> {'STALE' if stale else 'within 60 min'}")
        anchor_pin = solve_anchor(p1_pin[0], p1_pin[1], p1_pin[2], float(p_ou_pin[0]), line=line)
        grid_pin = joint_grid(anchor_pin, params, MAX_HALF)
    else:
        print(f"\n(ii) Pinnacle snapshot: {snap_name}")

    # --- margins (one table) ---------------------------------------------
    print_margin_table(margin_table(rows))

    # --- EV for every Soccer Bet market under each anchor -----------------
    status = family_status()
    priced = [(p, c, resolve(p, c), o) for p, c, o in rows if resolve(p, c).status == "OK"]
    results = []
    for prefix, code, market, odds in priced:
        p_sb, v_sb = price_grid(grid_sb, market)
        p_sb_eff = p_sb / (1 - v_sb) if v_sb < 1 - 1e-9 else p_sb
        row = {"market": f"{prefix}:{code}", "family": market.family, "odds": odds,
               "p_sb": p_sb_eff, "ev_sb": p_sb_eff * odds - 1.0,
               "family_status": status.get(market.family, "UNTESTED")}
        if grid_pin is not None:
            p_pin, v_pin = price_grid(grid_pin, market)
            p_pin_eff = p_pin / (1 - v_pin) if v_pin < 1 - 1e-9 else p_pin
            p_hair = p_pin_eff * (1 - HAIRCUT) + (1.0 / odds) * HAIRCUT
            row.update(p_pin=p_pin_eff, ev_pin=p_pin_eff * odds - 1.0, ev_pin_hair=p_hair * odds - 1.0)
        results.append(row)

    df = pd.DataFrame(results)
    df.to_csv(EV_CSV, index=False)

    n = len(df)
    pos_sb = int((df["ev_sb"] > 0).sum())
    print("\n--- positive-EV markets (headline) ---")
    print(f"  markets priced: {n}")
    print(f"  (i)  Soccer-Bet-anchored: {pos_sb} ({100 * pos_sb / n:.1f}%)")
    if "ev_pin" in df.columns:
        pos_pin = int((df["ev_pin"] > 0).sum())
        flagged = int((df["ev_pin_hair"] > 0.03).sum())
        print(f"  (ii) Pinnacle-anchored  : EV>0 {pos_pin} ({100 * pos_pin / n:.1f}%); "
              f"EV>+3% after a 20% haircut toward SB's own price: {flagged}")

    print(f"\n--- (ii) top 15 markets by EV on the Pinnacle anchor ---")
    if "ev_pin" in df.columns:
        top = df.nlargest(15, "ev_pin")
        print(f"  {'market':<20}{'family':<26}{'odds':>7}{'p_pin':>8}{'EV':>8}{'EV_hair':>9}  status")
        for r in top.itertuples(index=False):
            print(f"  {r.market:<20}{r.family:<26}{r.odds:>7.2f}{r.p_pin:>8.4f}"
                  f"{r.ev_pin:>8.4f}{r.ev_pin_hair:>9.4f}  {r.family_status}")
    else:
        print("  no Pinnacle snapshot")

    print("\n--- (ii) EV per 1X2 outcome on the Pinnacle anchor ---")
    for code, label in (("1", "home"), ("X", "draw"), ("2", "away")):
        r = df[df["market"] == f"FT:{code}"].iloc[0]
        print(f"  {label:<5} SB odds {r.odds:>5.2f} | p_pin {r.p_pin:.4f} | EV {r.ev_pin:+.4f}")

    print(f"\nwrote {EV_CSV}")
    return 0


if __name__ == "__main__":
    sys.exit(main())