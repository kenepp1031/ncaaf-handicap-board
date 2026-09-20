"""Roster-talent prior on team strength (247Sports Team Talent Composite).
See ingest/talent.py for the scrape half; this pulls each FBS team toward the
rating its roster implies while the model has seen little of it this season.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common import least_squares
from ingest.talent import key
from db.db import connect

MAX_WEIGHT = 0.2
FADE_GAMES = 8
MIN_FIT_TEAMS = 20


def load(season: int) -> dict:
    with connect() as con:
        rows = con.execute('SELECT * FROM talent WHERE season=?', (season,)).fetchall()
    return {r['school_key']: dict(r) for r in rows}


def lookup(stored: dict, team_name: str):
    return stored.get(key(team_name)) if team_name else None


def fit(stored: dict, ratings: dict, names: dict):
    pairs = []
    for team_id, r in ratings.items():
        row = lookup(stored, names.get(team_id, ''))
        if row and row.get('avg_rating') is not None and r.get('rating') is not None:
            pairs.append((row['avg_rating'], r['rating']))
    return least_squares(pairs, MIN_FIT_TEAMS)


def weight(season_games):
    if season_games is None or season_games >= FADE_GAMES or MAX_WEIGHT <= 0:
        return 0.0
    return MAX_WEIGHT * (1 - season_games / FADE_GAMES)


def team_shift(fitted, row, rating, season_games):
    w = weight(season_games)
    if not fitted or not row or row.get('avg_rating') is None or rating is None or w <= 0:
        return 0.0
    implied = fitted['intercept'] + fitted['slope'] * row['avg_rating']
    return round(w * (implied - rating), 3)


def margin_shift(fitted, home_row, away_row, home_rating, away_rating, home_games, away_games):
    if not fitted:
        return 0.0
    return round(team_shift(fitted, home_row, home_rating, home_games)
                 - team_shift(fitted, away_row, away_rating, away_games), 2)
