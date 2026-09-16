"""Spend-based early-season prior on team strength. See ingest/nil_spending.py
for the scrape/cache half; this is the fit()/margin_shift() math, unchanged
from nil.py, now reading its measure table from SQLite instead of a JSON cache.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ingest.nil_spending import key
from db.db import connect

MAX_WEIGHT = 0.35
FADE_GAMES = 8
MIN_FIT_TEAMS = 20

MEASURES = ('roster_cost', 'athletic_expenses')
MODEL_MEASURES = ('roster_cost',)


def load(season: int) -> dict:
    """school_key -> {'roster_cost':..., 'athletic_expenses':..., 'name':...}"""
    with connect() as con:
        rows = con.execute('SELECT * FROM nil_spend WHERE season=?', (season,)).fetchall()
    return {r['school_key']: dict(r) for r in rows}


def spending(stored: dict, team_name: str) -> dict:
    row = stored.get(key(team_name)) or {}
    return {'roster_cost': row.get('roster_cost'), 'athletic_expenses': row.get('athletic_expenses')}


def _least_squares(pairs):
    if len(pairs) < MIN_FIT_TEAMS:
        return None
    xs = [x for x, _ in pairs]
    ys = [y for _, y in pairs]
    mean_x, mean_y = sum(xs) / len(xs), sum(ys) / len(ys)
    sxx = sum((x - mean_x) ** 2 for x in xs)
    if sxx <= 0:
        return None
    slope = sum((x - mean_x) * (y - mean_y) for x, y in pairs) / sxx
    intercept = mean_y - slope * mean_x
    total = sum((y - mean_y) ** 2 for y in ys)
    residual = sum((y - (intercept + slope * x)) ** 2 for x, y in pairs)
    return {'slope': round(slope, 4), 'intercept': round(intercept, 4), 'teams': len(pairs),
            'r_squared': round(1 - residual / total, 4) if total else 0.0,
            'points_per_doubling': round(slope * math.log(2), 2)}


def fit(stored: dict, ratings: dict, names: dict):
    fits = {}
    for measure in MEASURES:
        pairs = []
        for team_id, r in ratings.items():
            row = stored.get(key(names.get(team_id, '')))
            dollars = row.get(measure) if row else None
            if dollars and dollars > 0 and r.get('rating') is not None:
                pairs.append((math.log(dollars), r['rating']))
        fitted = _least_squares(pairs)
        if fitted:
            fits[measure] = fitted
    return fits or None


def weight(season_games):
    if season_games is None or season_games >= FADE_GAMES or MAX_WEIGHT <= 0:
        return 0.0
    return MAX_WEIGHT * (1 - season_games / FADE_GAMES)


def implied_rating(fitted, dollars):
    return fitted['intercept'] + fitted['slope'] * math.log(dollars)


def team_shift(fitted, dollars, rating, season_games):
    w = weight(season_games)
    if not fitted or not dollars or dollars <= 0 or rating is None or w <= 0:
        return 0.0
    return round(w * (implied_rating(fitted, dollars) - rating), 3)


def shared_measure(fits, home_spend, away_spend):
    for measure in MODEL_MEASURES:
        if fits and fits.get(measure) and (home_spend or {}).get(measure) and (away_spend or {}).get(measure):
            return measure
    return None


def margin_shift(fits, home_spend, away_spend, home_rating, away_rating, home_games, away_games):
    measure = shared_measure(fits, home_spend, away_spend)
    if not measure:
        return 0.0, None
    fitted = fits[measure]
    home = team_shift(fitted, home_spend[measure], home_rating, home_games)
    away = team_shift(fitted, away_spend[measure], away_rating, away_games)
    return round(home - away, 2), measure


def leaderboard(stored: dict, limit=None):
    rows = []
    for k, row in stored.items():
        rows.append({'key': k, 'school': row.get('school_name', k),
                     'roster_cost': row.get('roster_cost'), 'athletic_expenses': row.get('athletic_expenses')})
    rows.sort(key=lambda r: (r['roster_cost'] is None, -(r['roster_cost'] or 0),
                             -(r['athletic_expenses'] or 0), r['school']))
    for i, row in enumerate(rows, 1):
        row['spend_rank'] = i
    return rows[:limit] if limit else rows
