"""Tests for the catalogue's ``ext_markets`` section.

The section must stay consistent with :mod:`core.soccerbet_ext`, must not touch
the base ``markets`` section, and must not re-list a market the base section
already expresses under a bare code (the duplicate bug the crashed auto-append
hit: 193 base markets reappeared as ``PREFIX:code``).
"""

from __future__ import annotations

import yaml

import step4_pricing
from core.soccerbet_ext import resolve
from step1_catalogue import settlement_signature
from step4_pricing import CATALOGUE

DOC = yaml.safe_load(CATALOGUE.read_text(encoding="utf-8"))
EXT = DOC["ext_markets"]

# (family, prefix, code) that must resolve UNTESTABLE
UNTESTABLE_KEYS = [
    ("FIRST_GOAL", "PDG", "1"),
    ("FIRST_GOAL", "PGC", "PG1&2+"),
    ("MINUTE_MARKETS", "M15", "1"),
    ("MINUTE_MARKETS", "M30", "G2+"),
]


def ext_codes() -> list[tuple[str, str, str]]:
    """(family, prefix, code) for every settleable ext market."""
    return [
        (family["family"], group["prefix"], code)
        for family in EXT["families"]
        for group in family["prefixes"]
        for code in group["codes"]
    ]


# --------------------------------------------------------------------------- #
# the base catalogue is untouched
# --------------------------------------------------------------------------- #
def test_base_section_is_intact():
    assert DOC["generated_by"] == "step1_catalogue.py"
    assert len(DOC["markets"]) == 207
    assert len(step4_pricing.load_markets()) == 207


def test_sections_are_separate():
    # the ext families live under their own key, never appended to `markets`
    assert "ext_markets" in DOC
    assert all(":" not in e["code"] for e in DOC["markets"])
    assert isinstance(EXT["families"], list)
    assert isinstance(EXT["untestable"], list)
    assert isinstance(EXT["unconfirmed"], list)


# --------------------------------------------------------------------------- #
# the ext section matches core.soccerbet_ext
# --------------------------------------------------------------------------- #
def test_every_ext_code_resolves_to_its_declared_family():
    for family, prefix, code in ext_codes():
        market = resolve(prefix, code)
        assert market.status == "OK", f"{prefix}:{code} is {market.status}"
        assert market.family == family, f"{prefix}:{code} -> {market.family}"


def recorded_coincidences() -> dict[str, str]:
    """{PREFIX:code -> the base market it settles like} from the catalogue."""
    doc = yaml.safe_load(CATALOGUE.read_text(encoding="utf-8"))
    out: dict[str, str] = {}
    for family in doc["ext_markets"]["families"]:
        for group in family["prefixes"]:
            out.update(group.get("settles_like_a_base_market", {}))
    return out


def test_ext_codes_that_repeat_a_base_market_are_recorded_not_hidden():
    """A printed code is kept inside a family the base does not cover.

    When such a code happens to settle like a base market it must be **recorded**,
    never silently dropped: e.g. `CS1:0:0` is the same bet as `GOAL_RANGE_1H I0`
    (no first-half goals), and `HRG:IX&ING` is the same bet again in its own section.
    """
    base: dict[tuple, str] = {}
    for market in step4_pricing.load_markets():
        base.setdefault(settlement_signature(market.outcome),
                        f"{market.family} {market.code}")
    recorded = recorded_coincidences()
    assert len(recorded) >= 3

    for _family, prefix, code in ext_codes():
        key = f"{prefix}:{code}"
        signature = settlement_signature(resolve(prefix, code).outcome)
        if signature in base:
            assert recorded.get(key) == base[signature], (
                f"{key} settles like {base[signature]} but is not recorded as such")
        else:
            assert key not in recorded, f"{key} is recorded as a duplicate but is not one"


def test_ext_codes_are_listed_once_each():
    """Distinct printed codes may settle identically (``DCG:12&0-2`` and
    ``DCG:12&1-2`` are both real book entries); the same key must not repeat."""
    keys = [f"{prefix}:{code}" for _family, prefix, code in ext_codes()]
    assert len(keys) == len(set(keys))


# --------------------------------------------------------------------------- #
# untestable and unconfirmed are flagged, never priced
# --------------------------------------------------------------------------- #
def test_untestable_families_are_listed_and_resolve_untestable():
    listed = {e["family"] for e in EXT["untestable"]}
    assert listed == {"FIRST_GOAL", "MINUTE_MARKETS"}
    for family, prefix, code in UNTESTABLE_KEYS:
        market = resolve(prefix, code)
        assert (market.family, market.status) == (family, "UNTESTABLE")
        assert group_of(family, prefix) is not None


def group_of(family: str, prefix: str) -> dict | None:
    for entry in EXT["untestable"]:
        if entry["family"] == family and prefix in entry["prefixes"]:
            return entry
    return None


def test_exactly_the_three_unconfirmed_codes_are_flagged():
    flagged = {f"{e['prefix']}:{e['code']}" for e in EXT["unconfirmed"]}
    assert flagged == {"SANSA:1vGG3+", "SANSA:2vGG3+", "SANSA:I2-3+vII3+"}
    for entry in EXT["unconfirmed"]:
        market = resolve(entry["prefix"], entry["code"])
        assert market.status == "UNCONFIRMED"
        assert entry["status"] == "UNCONFIRMED"
        assert market.family == entry["family"]


def test_no_unconfirmed_or_untestable_code_is_priced():
    priced = {f"{p}:{c}" for _f, p, c in ext_codes()}
    for entry in EXT["unconfirmed"]:
        assert f"{entry['prefix']}:{entry['code']}" not in priced


# --------------------------------------------------------------------------- #
# the ext markets are priceable through the same machinery as the base ones
# --------------------------------------------------------------------------- #
def test_ext_markets_are_priceable():
    markets = step4_pricing.load_ext_markets()
    assert len(markets) == len(ext_codes())
    masks = step4_pricing.market_masks(markets[:20], max_half=2)
    assert len(masks) == 20
    for win, void in masks.values():
        assert win.shape == void.shape
        assert set(win.tolist()) <= {0.0, 1.0}