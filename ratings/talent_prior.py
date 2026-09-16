"""Roster-talent prior on team strength (247Sports Team Talent Composite).
See ingest/talent.py for the scrape/cache half; this is the unchanged
fit()/margin_shift() math from talent.py, reading its measure from SQLite.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
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


def leaderboard(stored: dict):
    rows = list(stored.values())
    return sorted(rows, key=lambda r: (r.get('rank') is None, r.get('rank') or 0, r['school_name']))


def fit(stored: dict, ratings: dict, names: dict):
    pairs = []
    for team_id, r in ratings.items():
        row = lookup(stored, names.get(team_id, ''))
        if row and row.get('avg_rating') is not None and r.get('rating') is not None:
            pairs.append((row['avg_rating'], r['rating']))
    if len(pairs) < MIN_FIT_TEAMS:
        return None
    mean_x = sum(x for x, _ in pairs) / len(pairs)
    mean_y = sum(y for _, y in pairs) / len(pairs)
    sxx = sum((x - mean_x) ** 2 for x, _ in pairs)
    if sxx <= 0:
        return None
    slope = sum((x - mean_x) * (y - mean_y) for x, y in pairs) / sxx
    intercept = mean_y - slope * mean_x
    total = sum((y - mean_y) ** 2 for _, y in pairs)
    residual = sum((y - (intercept + slope * x)) ** 2 for x, y in pairs)
    return {'slope': round(slope, 4), 'intercept': round(intercept, 4), 'teams': len(pairs),
            'r_squared': round(1 - residual / total, 4) if total else 0.0}


def weight(season_games):
    if season_games is None or season_games >= FADE_GAMES or MAX_WEIGHT <= 0:
        return 0.0
    return MAX_WEIGHT * (1 - season_games / FADE_GAMES)


def implied_rating(fitted, avg_rating):
    return fitted['intercept'] + fitted['slope'] * avg_rating


def team_shift(fitted, row, rating, season_games):
    w = weight(season_games)
    if not fitted or not row or row.get('avg_rating') is None or rating is None or w <= 0:
        return 0.0
    return round(w * (implied_rating(fitted, row['avg_rating']) - rating), 3)


def margin_shift(fitted, home_row, away_row, home_rating, away_rating, home_games, away_games):
    if not fitted:
        return 0.0
    return round(team_shift(fitted, home_row, home_rating, home_games)
                 - team_shift(fitted, away_row, away_rating, away_games), 2)
