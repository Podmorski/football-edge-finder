"""Canonical league registry for the project.

Every league carries an explicit ``tier`` (division level within its country's
pyramid) and ``role`` so that same-named divisions in different tiers can never
be confused:

* ``role == "baseline"`` — the top-flight reference league (Bundesliga, ID 78).
* ``role == "target"``   — the in-scope leagues.

``football_data_code`` is football-data.co.uk's league code (also used in
``fixtures.csv``). ``penaltyblog`` / ``understat`` are the competition keys
understood by penaltyblog's scrapers (``None`` = not covered by that source).
"""

from __future__ import annotations

LEAGUES = [
    {
        "name": "2. Bundesliga",
        "tier": 2,
        "role": "target",
        "api_football_id": 79,
        "football_data_code": "D2",
        "penaltyblog": "DEU Bundesliga 2",
        "understat": None,
        "slug": "bundesliga_2",
    },
    {
        "name": "Bundesliga",
        "tier": 1,
        "role": "baseline",
        "api_football_id": 78,
        "football_data_code": "D1",
        "penaltyblog": "DEU Bundesliga 1",
        "understat": "DEU Bundesliga 1",
        "slug": "bundesliga_1",
    },
    {
        "name": "League One",
        "tier": 3,
        "role": "target",
        "api_football_id": 41,
        "football_data_code": "E2",
        "penaltyblog": "ENG League 1",
        "understat": None,
        "slug": "league_one_t3",
    },
    {
        "name": "Ligue 2",
        "tier": 2,
        "role": "target",
        "api_football_id": 62,
        "football_data_code": "F2",
        "penaltyblog": "FRA Ligue 2",
        "understat": None,
        "slug": "ligue_2_t2",
    },
]


def label_of(league: dict) -> str:
    """Consistent human label, e.g. '2. Bundesliga (tier 2, target)'."""
    return f"{league['name']} (tier {league['tier']}, {league['role']})"