"""Team-level penalty-tendency prior on projected margin. See
ingest/officiating.py for the box-score fetch half; this is the unchanged
fit()/margin_shift() math from officiating.py, reading from SQLite.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common import least_squares
from db.db import connect

# Disabled 2026-09-20. Walk-forward over 786 FBS-vs-FBS games (2025-26) measured
# this prior as the worst of the three: MAE 13.164 with it alone vs 13.070 with all
# priors off, and 50.7% ATS vs 52.9%. Penalty differential is mostly game script and
# opponent quality, not a team trait, and fit() regresses it on the very ratings it
# then adjusts. Set back to 0.15 only with a walk-forward that shows it earning its
# place.
MAX_WEIGHT = 0.0
FULL_SAMPLE_GAMES = 6
MIN_FIT_TEAMS = 20


def team_rates(games: list[dict]) -> dict:
    """games: rows with home_id/away_id/completed + a joined officiating_penalties row.
    Returns per-team penalty tendency: own penalties and penalties drawn, per game.
    """
    totals = {}
    for g in games:
        if not g.get('completed') or g.get('home_penalties') is None or g.get('away_penalties') is None:
            continue
        for side, other in (('home', 'away'), ('away', 'home')):
            tid = g[side + '_id']
            t = totals.setdefault(tid, {'games': 0, 'own': 0, 'own_yards': 0, 'drawn': 0, 'drawn_yards': 0,
                                         'home_games': 0, 'home_own': 0, 'away_games': 0, 'away_own': 0})
            t['games'] += 1
            t['own'] += g[side + '_penalties']
            t['own_yards'] += g[side + '_penalty_yards'] or 0
            t['drawn'] += g[other + '_penalties']
            t['drawn_yards'] += g[other + '_penalty_yards'] or 0
            t[side + '_games'] += 1
            t[side + '_own'] += g[side + '_penalties']
    rates = {}
    for tid, t in totals.items():
        rates[tid] = {'games': t['games'],
                      'penalties_per_game': round(t['own'] / t['games'], 2),
                      'penalty_yards_per_game': round(t['own_yards'] / t['games'], 1),
                      'drawn_per_game': round(t['drawn'] / t['games'], 2),
                      'net_penalty_margin': round(t['drawn'] / t['games'] - t['own'] / t['games'], 2),
                      'home_penalties_per_game': round(t['home_own'] / t['home_games'], 2) if t['home_games'] else None,
                      'away_penalties_per_game': round(t['away_own'] / t['away_games'], 2) if t['away_games'] else None}
    return rates


def load_rates(season: int) -> dict:
    with connect() as con:
        rows = con.execute(
            """SELECT g.home_id, g.away_id, g.completed,
                      p.home_penalties, p.home_penalty_yards, p.away_penalties, p.away_penalty_yards
               FROM games g JOIN officiating_penalties p ON p.game_id = g.game_id
               WHERE g.season=?""", (season,)).fetchall()
    return team_rates([dict(r) for r in rows])


def fit(ratings: dict, rates: dict):
    pairs = [(rates[tid]['net_penalty_margin'], r['rating'])
             for tid, r in ratings.items() if tid in rates and r.get('rating') is not None]
    return least_squares(pairs, MIN_FIT_TEAMS)


def weight(games):
    if not games or MAX_WEIGHT <= 0:
        return 0.0
    return MAX_WEIGHT * min(1.0, games / FULL_SAMPLE_GAMES)


def team_shift(fitted, rate, rating):
    if not fitted or not rate or rating is None:
        return 0.0
    w = weight(rate['games'])
    if w <= 0:
        return 0.0
    implied = fitted['intercept'] + fitted['slope'] * rate['net_penalty_margin']
    return round(w * (implied - rating), 3)


def margin_shift(fitted, home_rate, away_rate, home_rating, away_rating):
    if not fitted:
        return 0.0
    home = team_shift(fitted, home_rate, home_rating)
    away = team_shift(fitted, away_rate, away_rating)
    return round(home - away, 2)
