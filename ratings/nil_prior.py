"""Roster-cost prior on team strength, for the early season when the model has
seen little of a team. See ingest/nil_spending.py for the scrape half.

Athletic-department expenses are ingested alongside roster cost but never move
a line: fitted across FBS and FCS together they pulled projections away from
the market (see CHANGELOG-2026-09-09.md), so only roster cost is used here.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common import least_squares
from ingest.nil_spending import key
from db.db import connect

MAX_WEIGHT = 0.35
FADE_GAMES = 8
MIN_FIT_TEAMS = 20


def load(season: int) -> dict:
    """school_key -> nil_spend row"""
    with connect() as con:
        rows = con.execute('SELECT * FROM nil_spend WHERE season=?', (season,)).fetchall()
    return {r['school_key']: dict(r) for r in rows}


def roster_cost(stored: dict, team_name: str):
    return (stored.get(key(team_name)) or {}).get('roster_cost')


def fit(stored: dict, ratings: dict, names: dict):
    pairs = []
    for team_id, r in ratings.items():
        dollars = roster_cost(stored, names.get(team_id, ''))
        if dollars and dollars > 0 and r.get('rating') is not None:
            pairs.append((math.log(dollars), r['rating']))
    fitted = least_squares(pairs, MIN_FIT_TEAMS)
    if fitted:
        fitted['points_per_doubling'] = round(fitted['slope'] * math.log(2), 2)
    return fitted


def weight(season_games):
    if season_games is None or season_games >= FADE_GAMES or MAX_WEIGHT <= 0:
        return 0.0
    return MAX_WEIGHT * (1 - season_games / FADE_GAMES)


def team_shift(fitted, dollars, rating, season_games):
    w = weight(season_games)
    if not fitted or not dollars or dollars <= 0 or rating is None or w <= 0:
        return 0.0
    implied = fitted['intercept'] + fitted['slope'] * math.log(dollars)
    return round(w * (implied - rating), 3)


def margin_shift(fitted, home_cost, away_cost, home_rating, away_rating, home_games, away_games):
    """Points added to the home margin. Zero unless both schools report a roster cost."""
    if not fitted or not home_cost or not away_cost:
        return 0.0
    return round(team_shift(fitted, home_cost, home_rating, home_games)
                 - team_shift(fitted, away_cost, away_rating, away_games), 2)
