"""Market-anchored half-by-half scoreline model.

Layers
------
**L1 anchor** — per match, solve ``(lambda, mu)`` so a Dixon-Coles full-time grid
reproduces the de-margined **pre-match** 1X2 and O/U 2.5 (least squares).

**L2 half split** — the first-half share of each team's goal rate, estimated on
training seasons only, allowed to depend on total expected goals and favourite
strength.

**L3 game state** — Dixon-Robinson (1998) style: second-half rates are multiplied
by factors depending on the half-time state (leading / level / trailing, by side),
estimated leakage-free.

Output is a joint grid over ``(h1, a1, h2, a2)``; every catalogue market is
derived from it via :mod:`core.market_code`.

Baselines
---------
``B0`` — same L1 anchor, fixed 50/50 split, independent halves (a plausible
"book formula"). ``B1`` — B0 with a 45/55 split.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy.optimize import minimize
from scipy.stats import poisson

from core.market_code import LOSE, VOID, WIN, Market

MAX_HALF_GOALS = 10
DEFAULT_RHO = -0.05


# --------------------------------------------------------------------------- #
# L1 anchor
# --------------------------------------------------------------------------- #
@dataclass
class Anchor:
    lam: float
    mu: float
    residual: float


def _dc_grid(lam: float, mu: float, rho: float, max_goals: int) -> np.ndarray:
    """Independent-Poisson grid with the Dixon-Coles low-score adjustment."""
    h = poisson.pmf(np.arange(max_goals + 1), lam)
    a = poisson.pmf(np.arange(max_goals + 1), mu)
    grid = np.outer(h, a)
    grid[0, 0] *= 1.0 - rho * lam * mu
    grid[1, 0] *= 1.0 + rho * lam
    grid[0, 1] *= 1.0 + rho * mu
    grid[1, 1] *= 1.0 - rho
    grid = np.clip(grid, 0.0, None)
    return grid / grid.sum()


def _ft_probs(grid: np.ndarray) -> tuple[float, float, float, float]:
    i, j = np.indices(grid.shape)
    home = float(grid[i > j].sum())
    draw = float(grid[i == j].sum())
    away = float(grid[i < j].sum())
    over = float(grid[(i + j) >= 3].sum())
    return home, draw, away, over


def solve_anchor(
    p_home: float, p_draw: float, p_away: float, p_over25: float,
    rho: float = DEFAULT_RHO, max_goals: int = 15,
) -> Anchor:
    """Least-squares fit of (lambda, mu) to the de-margined pre-match market.

    Uses L-BFGS-B on the log-rates: gradient-based, so it converges in tens of
    iterations rather than the thousands a Nelder-Mead restart would need.
    """
    target = np.array([p_home, p_draw, p_away, p_over25])

    def objective(params):
        lam, mu = np.exp(params)
        grid = _dc_grid(lam, mu, rho, max_goals)
        return float(np.sum((np.array(_ft_probs(grid)) - target) ** 2))

    bounds = [(np.log(0.05), np.log(6.0)), (np.log(0.05), np.log(6.0))]
    best = None
    for x0 in ([np.log(1.4), np.log(1.1)], [np.log(1.0), np.log(1.0)]):
        res = minimize(objective, x0=x0, method="L-BFGS-B", bounds=bounds,
                       options={"maxiter": 200, "ftol": 1e-14, "gtol": 1e-10})
        if best is None or res.fun < best.fun:
            best = res
    lam, mu = np.exp(best.x)
    return Anchor(lam=float(lam), mu=float(mu), residual=float(np.sqrt(best.fun)))


# --------------------------------------------------------------------------- #
# L2 + L3 parameters
# --------------------------------------------------------------------------- #
@dataclass
class HalfParams:
    split_a: float = 0.5
    split_b: float = 0.0
    split_c: float = 0.0
    state_mult: dict = field(default_factory=dict)
    ht_draw_inflation: float = 1.0

    def first_half_share(self, lam: float, mu: float) -> float:
        share = self.split_a + self.split_b * (lam + mu) + self.split_c * abs(lam - mu)
        return float(min(max(share, 0.30), 0.70))


def _state(h1: int, a1: int) -> str:
    if h1 > a1:
        return "home_lead"
    if h1 < a1:
        return "away_lead"
    return "level"


def fit_half_params(rows: list[dict], rho: float = DEFAULT_RHO) -> HalfParams:
    """Estimate L2 (split) and L3 (game-state) from training rows.

    Each row needs: lam, mu, hth, hta, fth, fta.
    """
    # --- L2: regress the observed first-half share on (lam+mu) and |lam-mu| ---
    x, y = [], []
    for r in rows:
        total = r["fth"] + r["fta"]
        if total <= 0:
            continue
        x.append([1.0, r["lam"] + r["mu"], abs(r["lam"] - r["mu"])])
        y.append((r["hth"] + r["hta"]) / total)
    if len(x) >= 30:
        beta, *_ = np.linalg.lstsq(np.asarray(x), np.asarray(y), rcond=None)
        params = HalfParams(split_a=float(beta[0]), split_b=float(beta[1]), split_c=float(beta[2]))
    else:
        params = HalfParams()

    # --- L3: ratio estimator of second-half multipliers by HT state ---
    num = {("home", s): 0.0 for s in ("home_lead", "level", "away_lead")}
    den = {("home", s): 0.0 for s in ("home_lead", "level", "away_lead")}
    num.update({("away", s): 0.0 for s in ("home_lead", "level", "away_lead")})
    den.update({("away", s): 0.0 for s in ("home_lead", "level", "away_lead")})

    for r in rows:
        share = params.first_half_share(r["lam"], r["mu"])
        state = _state(r["hth"], r["hta"])
        exp_h2 = r["lam"] * (1 - share)
        exp_a2 = r["mu"] * (1 - share)
        num[("home", state)] += r["fth"] - r["hth"]
        den[("home", state)] += exp_h2
        num[("away", state)] += r["fta"] - r["hta"]
        den[("away", state)] += exp_a2

    mult = {}
    for key in num:
        mult[key] = float(num[key] / den[key]) if den[key] > 1e-9 else 1.0
    # shrink toward 1.0 to avoid over-fitting sparse states
    params.state_mult = {k: float(0.5 * v + 0.5 * 1.0) for k, v in mult.items()}
    return params


# --------------------------------------------------------------------------- #
# joint grid
# --------------------------------------------------------------------------- #
def joint_grid(
    anchor: Anchor,
    params: HalfParams | None = None,
    max_half: int = MAX_HALF_GOALS,
    fixed_share: float | None = None,
    use_state: bool = True,
) -> np.ndarray:
    """Joint P(h1, a1, h2, a2), shape (max_half+1,)*4."""
    lam, mu = anchor.lam, anchor.mu
    if fixed_share is not None:
        share_h = share_a = fixed_share
    elif params is not None:
        share_h = share_a = params.first_half_share(lam, mu)
    else:
        share_h = share_a = 0.5

    h1_pmf = poisson.pmf(np.arange(max_half + 1), lam * share_h)
    a1_pmf = poisson.pmf(np.arange(max_half + 1), mu * share_a)
    first = np.outer(h1_pmf, a1_pmf)

    grid = np.zeros((max_half + 1,) * 4)
    for h1 in range(max_half + 1):
        for a1 in range(max_half + 1):
            p1 = first[h1, a1]
            if p1 <= 0:
                continue
            state = _state(h1, a1)
            mult_h = params.state_mult.get(("home", state), 1.0) if (use_state and params) else 1.0
            mult_a = params.state_mult.get(("away", state), 1.0) if (use_state and params) else 1.0
            lam2 = lam * (1 - share_h) * mult_h
            mu2 = mu * (1 - share_a) * mult_a
            h2_pmf = poisson.pmf(np.arange(max_half + 1), lam2)
            a2_pmf = poisson.pmf(np.arange(max_half + 1), mu2)
            grid[h1, a1] = p1 * np.outer(h2_pmf, a2_pmf)

    total = grid.sum()
    if total <= 0:
        raise ValueError("joint grid has zero mass")
    return grid / total


def market_prob(grid: np.ndarray, market: Market) -> tuple[float, float]:
    """Return (p_win, p_void) for a market under the joint grid."""
    max_half = grid.shape[0] - 1
    win = void = 0.0
    for h1 in range(max_half + 1):
        for a1 in range(max_half + 1):
            for h2 in range(max_half + 1):
                for a2 in range(max_half + 1):
                    p = grid[h1, a1, h2, a2]
                    if p <= 0:
                        continue
                    out = market.outcome(h1, a1, h1 + h2, a1 + a2)
                    if out == WIN:
                        win += p
                    elif out == VOID:
                        void += p
    return float(win), float(void)


def fair_odds(p_win: float, p_void: float = 0.0) -> float:
    """Fair decimal odds, treating void as a returned stake."""
    denom = 1.0 - p_void
    if p_win <= 0 or denom <= 0:
        return float("inf")
    return denom / p_win


def baselines(anchor: Anchor, max_half: int = MAX_HALF_GOALS) -> dict[str, np.ndarray]:
    """B0 = 50/50 split, independent halves; B1 = 45/55 split."""
    return {
        "B0": joint_grid(anchor, None, max_half, fixed_share=0.5, use_state=False),
        "B1": joint_grid(anchor, None, max_half, fixed_share=0.45, use_state=False),
    }


# --------------------------------------------------------------------------- #
# vectorised batch helpers (needed: ~12k matches x 207 markets)
# --------------------------------------------------------------------------- #
def market_masks(markets: list[Market], max_half: int = MAX_HALF_GOALS) -> dict:
    """Flattened (win, void) boolean masks per market code, computed once."""
    idx = np.indices((max_half + 1,) * 4).reshape(4, -1)
    h1, a1, h2, a2 = idx
    fth, fta = h1 + h2, a1 + a2
    out = {}
    for market in markets:
        win = np.zeros(idx.shape[1], dtype=np.float64)
        void = np.zeros(idx.shape[1], dtype=np.float64)
        for i in range(idx.shape[1]):
            outcome = market.outcome(int(h1[i]), int(a1[i]), int(fth[i]), int(fta[i]))
            if outcome == WIN:
                win[i] = 1.0
            elif outcome == VOID:
                void[i] = 1.0
        out[market.code] = (win, void)
    return out


def batch_market_probs(grids_flat: np.ndarray, masks: dict) -> dict:
    """grids_flat: (n_matches, cells). Returns {code: (p_win, p_void)} arrays."""
    out = {}
    for code, (win, void) in masks.items():
        out[code] = (grids_flat @ win, grids_flat @ void)
    return out


def grids_to_flat(grids: list[np.ndarray]) -> np.ndarray:
    return np.vstack([g.reshape(-1) for g in grids])