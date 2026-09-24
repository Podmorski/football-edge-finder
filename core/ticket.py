"""Accumulator (ticket) EV with a legs-based bonus schedule.

The bonus schedule is a **PLACEHOLDER** until the user supplies Soccer Bet's
actual schedule. It is a parameter, clearly labelled, and defaults to no bonus.
"""

from __future__ import annotations

from dataclasses import dataclass, field

DEFAULT_CAP = 3

# PLACEHOLDER — replace with Soccer Bet's real schedule.
BONUS_SCHEDULE_PLACEHOLDER: dict[int, float] = {1: 0.0, 2: 0.0, 3: 0.0}


@dataclass
class Leg:
    code: str
    family: str
    odds: float
    p_model: float
    p_void: float = 0.0

    @property
    def effective_odds(self) -> float:
        """Odds adjusted for a void leg (stake returned)."""
        return self.odds


@dataclass
class Ticket:
    legs: list[Leg] = field(default_factory=list)
    bonus_schedule: dict[int, float] = field(default_factory=lambda: dict(BONUS_SCHEDULE_PLACEHOLDER))
    cap: int = DEFAULT_CAP

    def add(self, leg: Leg) -> None:
        if len(self.legs) >= self.cap:
            raise ValueError(f"ticket cap is {self.cap} legs")
        self.legs.append(leg)

    @property
    def combined_odds(self) -> float:
        out = 1.0
        for leg in self.legs:
            out *= leg.odds
        return out

    @property
    def p_win(self) -> float:
        out = 1.0
        for leg in self.legs:
            out *= leg.p_model
        return out

    @property
    def bonus(self) -> float:
        return float(self.bonus_schedule.get(len(self.legs), 0.0))

    @property
    def ev(self) -> float:
        """EV per unit staked, including the placeholder bonus."""
        return self.p_win * self.combined_odds * (1.0 + self.bonus) - 1.0

    def summary(self) -> dict:
        return {
            "legs": len(self.legs),
            "combined_odds": self.combined_odds,
            "p_win": self.p_win,
            "bonus": self.bonus,
            "ev": self.ev,
            "bonus_schedule": "PLACEHOLDER",
        }
