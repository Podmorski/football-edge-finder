"""Mozzart (PulseScore) market mapping.

Mozzart prints its own Serbian section names (``rawName``) and codes, and **the
section decides what a code means**, exactly as with Soccer Bet. This module maps
a Mozzart ``(section, period, code)`` to one of our catalogue markets and reuses
the existing settlement machinery:

* a ``family`` rule settles through :func:`core.market_code.parse`;
* a ``prefix`` rule settles through :func:`core.soccerbet_ext.resolve`.

Anything not matched is **UNMAPPED** — listed, never guessed. The per-selection
``moreInfo.description`` is kept in the raw JSON under ``data/mozzart/raw/`` for
audit; it is not needed to settle a market.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from core.market_code import Market, direct_markets, parse
from core.soccerbet_ext import ExtMarket, resolve as resolve_ext

CONFIG = Path("config/mozzart_market_map.yaml")
CATALOGUE = Path("config/markets_catalogue.yaml")
UNMAPPED = "UNMAPPED"


@dataclass(frozen=True)
class Rule:
    section: str
    period: str
    family: str | None = None
    prefix: str | None = None
    code_map: dict[str, str] = field(default_factory=dict)
    code_prefix: str | None = None
    codes: tuple[str, ...] | None = None

    def matches(self, code: str) -> bool:
        if self.codes is not None and code not in self.codes:
            return False
        if self.code_prefix is not None and not code.startswith(self.code_prefix):
            return False
        return True

    @property
    def specific(self) -> bool:
        return self.codes is not None or self.code_prefix is not None


_RULES: list[Rule] | None = None
_VALID: set[tuple[str, str]] | None = None
_DIRECT: dict[tuple[str, str], Market] | None = None


def _norm(code: str) -> str:
    """Codes are compared ignoring spacing: Mozzart prints `1&2+`, we print `1 & 2+`."""
    return code.replace(" ", "")


def _valid_pairs() -> set[tuple[str, str]]:
    """Every (family, code) the catalogue actually carries, spacing-normalised."""
    global _VALID
    if _VALID is None:
        doc = yaml.safe_load(CATALOGUE.read_text(encoding="utf-8"))
        pairs = {(e["family"], _norm(e["code"])) for e in doc["markets"]}
        for family in doc.get("ext_markets", {}).get("families", []):
            for group in family["prefixes"]:
                for code in group["codes"]:
                    pairs.add((family["family"], _norm(code)))
        _VALID = pairs
    return _VALID


def _direct() -> dict[tuple[str, str], Market]:
    global _DIRECT
    if _DIRECT is None:
        _DIRECT = {(m.family, m.code): m for m in direct_markets()}
    return _DIRECT


def load_rules(path: Path | None = None) -> list[Rule]:
    global _RULES
    if path is None and _RULES is not None:
        return _RULES
    doc = yaml.safe_load(Path(path or CONFIG).read_text(encoding="utf-8"))
    rules = [
        Rule(
            section=entry["section"],
            period=entry["period"],
            family=entry.get("family"),
            prefix=entry.get("prefix"),
            code_map=entry.get("code_map") or {},
            code_prefix=entry.get("code_prefix"),
            codes=tuple(entry["codes"]) if entry.get("codes") else None,
        )
        for entry in doc["rules"]
    ]
    if path is None:
        _RULES = rules
    return rules


def _pick(section: str, period: str, code: str) -> Rule | None:
    """The most specific rule for (section, period, code), or None."""
    candidates = [r for r in load_rules()
                  if r.section == section and r.period == period and r.matches(code)]
    if not candidates:
        return None
    specific = [r for r in candidates if r.specific]
    return (specific or candidates)[0]


def resolve(section: str, period: str, code: str) -> Market | ExtMarket | None:
    """Map a Mozzart ``(section, period, code)`` to a catalogue market.

    Returns a :class:`core.market_code.Market` or
    :class:`core.soccerbet_ext.ExtMarket`, or ``None`` when the market is
    UNMAPPED. A rule whose code is not a code the catalogue actually carries is
    also UNMAPPED rather than guessed.
    """
    rule = _pick(section, period, code)
    if rule is None:
        return None
    our_code = rule.code_map.get(code, code)
    market: Market | ExtMarket | None = None
    if rule.family:
        market = _direct().get((rule.family, our_code))
        if market is None:
            try:
                market = parse(our_code, rule.family)
            except ValueError:
                return None
    elif rule.prefix:
        ext = resolve_ext(rule.prefix, our_code)
        market = None if ext.status != "OK" else ext
    if market is None:
        return None
    if (market.family, _norm(market.code)) not in _valid_pairs():
        return None
    return market


def unmapped_sections(rows: list[dict]) -> dict[tuple[str, str], list[str]]:
    """Group the codes of a raw market list that do not map.

    ``rows`` is a list of ``{"section", "period", "code"}`` dicts (one per
    selection). Returns ``{(section, period): [codes]}`` for the UNMAPPED ones.
    """
    out: dict[tuple[str, str], list[str]] = {}
    for row in rows:
        if resolve(row["section"], row["period"], row["code"]) is None:
            out.setdefault((row["section"], row["period"]), []).append(row["code"])
    return out