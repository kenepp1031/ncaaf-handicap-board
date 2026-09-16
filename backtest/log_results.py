"""Grade completed games' projections against the market once final scores land.
Sport-generic logic, adapted from NFL 2.0's backtest/log_results.py.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from db.db import connect


def _closing_spread(con, game_id):
    row = con.execute(
        """SELECT home_spread, total FROM line_history WHERE game_id=?
           ORDER BY captured_at DESC LIMIT 1""", (game_id,)).fetchone()
    if row:
        return row['home_spread'], row['total']
    row = con.execute('SELECT home_spread, total FROM games WHERE game_id=?', (game_id,)).fetchone()
    return (row['home_spread'], row['total']) if row else (None, None)


def _ats_result(predicted_spread, closing_spread, home_score, away_score):
    if closing_spread is None:
        return None
    margin = home_score - away_score
    edge = predicted_spread - closing_spread if predicted_spread is not None else None
    if edge is None or abs(edge) < 1e-9:
        return None
    home_side = edge < 0  # more negative predicted spread = model likes home more
    covered = margin + closing_spread
    if covered == 0:
        return 'push'
    covered_home = covered > 0
    return 'win' if covered_home == home_side else 'loss'


def _ou_result(predicted_total, closing_total, home_score, away_score):
    if closing_total is None or predicted_total is None:
        return None
    actual = home_score + away_score
    if actual == closing_total:
        return 'push'
    predicted_over = predicted_total > closing_total
    actual_over = actual > closing_total
    return 'win' if predicted_over == actual_over else 'loss'


def log_season(season: int) -> int:
    with connect() as con:
        games = con.execute(
            """SELECT g.game_id, g.season, g.week, g.home_score, g.away_score,
                      p.fair_home_spread, p.projected_total, p.confidence
               FROM games g JOIN projections p ON p.game_id = g.game_id
               WHERE g.season=? AND g.completed=1""", (season,)).fetchall()
        n = 0
        for g in games:
            closing_spread, closing_total = _closing_spread(con, g['game_id'])
            error_spread = None if closing_spread is None or g['fair_home_spread'] is None else round(
                (g['home_score'] - g['away_score']) - (-g['fair_home_spread']), 2)
            error_total = None if g['projected_total'] is None else round(
                (g['home_score'] + g['away_score']) - g['projected_total'], 2)
            ats = _ats_result(g['fair_home_spread'], closing_spread, g['home_score'], g['away_score'])
            ou = _ou_result(g['projected_total'], closing_total, g['home_score'], g['away_score'])
            con.execute(
                """INSERT INTO backtest_log (game_id, season, week, predicted_spread, closing_spread, error_spread,
                        predicted_total, closing_total, error_total, ats_result, ou_result, confidence)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(game_id) DO UPDATE SET
                       predicted_spread=excluded.predicted_spread, closing_spread=excluded.closing_spread,
                       error_spread=excluded.error_spread, predicted_total=excluded.predicted_total,
                       closing_total=excluded.closing_total, error_total=excluded.error_total,
                       ats_result=excluded.ats_result, ou_result=excluded.ou_result, confidence=excluded.confidence""",
                (g['game_id'], g['season'], g['week'], g['fair_home_spread'], closing_spread, error_spread,
                 g['projected_total'], closing_total, error_total, ats, ou, g['confidence']))
            n += 1
        con.commit()
    return n


if __name__ == '__main__':
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument('season', type=int)
    a = p.parse_args()
    print(f'Logged {log_season(a.season)} games')
