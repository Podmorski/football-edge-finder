"""Team-name matching shared by the bet log, the fair sheet and the audits.

Names arrive from three sources — **Mozzart** (PulseScore), **The Odds API** and
the **historical** parquet — and are spelled differently (``Burton Albion`` vs
``Burton``). Matching is heuristic: strip club noise, apply the evidenced aliases
in ``config/team_aliases.yaml``, and compare with a similarity ratio. Two clubs
that look alike but are different (the locked ``non_merge`` pairs) never match.
"""

from __future__ import annotations

import difflib
import re
import unicodedata
from functools import lru_cache
from pathlib import Path

import yaml

ALIASES = Path("config/team_aliases.yaml")

MATCH_SIMILARITY = 0.70

# Tokens that carry no identifying information about a club.
_NOISE = {
    "fc", "cf", "sc", "ac", "afc", "sv", "vfl", "vfb", "tsg", "bsc", "fk", "sk",
    "nk", "hk", "cd", "ud", "sd", "as", "ss", "ssc", "usl", "ev", "e", "v",
    "1", "ii", "b", "u19", "u21", "04", "05", "07", "09", "1846", "1899",
}


def tokens(name: str) -> list[str]:
    text = unicodedata.normalize("NFKD", str(name)).encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-z0-9 ]", " ", text.lower())
    return [token for token in text.split() if token not in _NOISE]


def _key(name: str) -> str:
    return " ".join(tokens(name))


@lru_cache(maxsize=1)
def alias_map() -> dict[str, str]:
    """Variant spelling -> canonical name, from ``config/team_aliases.yaml``.

    Only evidenced variants are listed. A wrong alias silently corrupts team
    strength, so the list stays short and is backed by a team audit.
    """
    if not ALIASES.exists():
        return {}
    doc = yaml.safe_load(ALIASES.read_text(encoding="utf-8")) or {}
    out: dict[str, str] = {}
    for entry in doc.get("aliases") or []:
        variant = _key(entry.get("variant", ""))
        canonical = _key(entry.get("canonical", ""))
        if variant and canonical:
            out[variant] = canonical
    return out


@lru_cache(maxsize=1)
def non_merge_pairs() -> set[frozenset[str]]:
    """Club pairs that look similar but are different clubs — never merged."""
    if not ALIASES.exists():
        return set()
    doc = yaml.safe_load(ALIASES.read_text(encoding="utf-8")) or {}
    pairs = set()
    for entry in doc.get("non_merge") or []:
        left, right = _key(entry.get("a", "")), _key(entry.get("b", ""))
        if left and right:
            pairs.add(frozenset({left, right}))
    return pairs


def similarity(a: str, b: str) -> float:
    aliases = alias_map()
    left = aliases.get(_key(a), _key(a))
    right = aliases.get(_key(b), _key(b))
    if not left or not right:
        return 0.0
    if frozenset({left, right}) in non_merge_pairs():
        return 0.0
    if left == right:
        return 1.0
    return difflib.SequenceMatcher(None, left, right).ratio()


def best_match(name: str, candidates) -> tuple[str | None, float]:
    best, score = None, 0.0
    for candidate in candidates:
        value = similarity(name, candidate)
        if value > score:
            best, score = candidate, value
    return best, score