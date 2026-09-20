"""Grade completed games against the number we actually published, using only
forecasts made before kickoff.

Three things this deliberately does differently from the first version:

* It reads `projection_snapshots`, not `projections`. The latter is a current-view
  row per game that every run overwrites, so it could never answer "what did we
  say on Friday?" -- and a backfill run would write a post-kickoff projection and
  freeze it there. Snapshots are append-only and written only before kickoff.
* It grades `lean_home_spread`, the number the dashboard shows, not the raw model
  line. The old version graded `fair_home_spread`, so the record described a
  number nobody bet.
* It records the edge and the pooled-FCS flag on every row, so the report can
  bucket by edge and keep FBS-vs-FCS blowouts out of the headline accuracy.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from db.db import connect


def _closing_line(con, game_id, kickoff):
    """Last spread and last total observed strictly before kickoff.

    Tracked separately on purpose: the DraftKings Network feed carries a spread
    far more often than a total (273 totals in 747 rows), so taking both fields
    off whichever row happens to be newest threw away a perfectly good total from
    an earlier capture and left every game ungraded for Over/Under.
    """
    spread = total = None
    for r in con.execute(
            """SELECT home_spread, total FROM line_history
               WHERE game_id=? AND captured_at < ? ORDER BY captured_at""", (game_id, kickoff)):
        if r['home_spread'] is not None:
            spread = r['home_spread']
        if r['total'] is not None:
            total = r['total']
    if spread is None or total is None:
        row = con.execute('SELECT home_spread, total FROM games WHERE game_id=?', (game_id,)).fetchone()
        if row:
            spread = spread if spread is not None else row['home_spread']
            total = total if total is not None else row['total']
    return spread, total


def _ats_result(graded_spread, closing_spread, home_score, away_score):
    if closing_spread is None or graded_spread is None:
        return None, None
    edge = graded_spread - closing_spread
    if abs(edge) < 1e-9:
        return None, 0.0
    home_side = edge < 0  # more negative than the market = the model likes the home team
    covered = (home_score - away_score) + closing_spread
    if covered == 0:
        return 'push', round(-edge, 2)
    return ('win' if (covered > 0) == home_side else 'loss'), round(-edge, 2)


def _ou_result(predicted_total, closing_total, home_score, away_score):
    if closing_total is None or predicted_total is None:
        return None
    actual = home_score + away_score
    if actual == closing_total:
        return 'push'
    return 'win' if (predicted_total > closing_total) == (actual > closing_total) else 'loss'


def log_season(season: int) -> int:
    with connect() as con:
        games = con.execute(
            """SELECT g.game_id, g.season, g.week, g.home_score, g.away_score, g.kickoff
               FROM games g WHERE g.season=? AND g.completed=1
                 AND g.home_score IS NOT NULL AND g.away_score IS NOT NULL""", (season,)).fetchall()
        n = 0
        for g in games:
            # The last forecast published before this game kicked off, and nothing else.
            s = con.execute(
                """SELECT * FROM projection_snapshots WHERE game_id=? AND generated_at < ?
                   ORDER BY generated_at DESC LIMIT 1""", (g['game_id'], g['kickoff'])).fetchone()
            if not s:
                continue
            graded = s['lean_home_spread'] if s['lean_home_spread'] is not None else s['fair_home_spread']
            closing_spread, closing_total = _closing_line(con, g['game_id'], g['kickoff'])
            margin = g['home_score'] - g['away_score']
            error_spread = None if graded is None else round(margin - (-graded), 2)
            error_total = None if s['projected_total'] is None else round(
                (g['home_score'] + g['away_score']) - s['projected_total'], 2)
            ats, edge = _ats_result(graded, closing_spread, g['home_score'], g['away_score'])
            ou = _ou_result(s['projected_total'], closing_total, g['home_score'], g['away_score'])
            pooled = 1 if json.loads(s['pooled_fcs_json'] or '[]') else 0
            con.execute(
                """INSERT INTO backtest_log (game_id, season, week, predicted_spread, closing_spread, error_spread,
                        predicted_total, closing_total, error_total, ats_result, ou_result, confidence,
                        graded_spread, edge_points, pooled_fcs, generated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(game_id) DO UPDATE SET
                       predicted_spread=excluded.predicted_spread, closing_spread=excluded.closing_spread,
                       error_spread=excluded.error_spread, predicted_total=excluded.predicted_total,
                       closing_total=excluded.closing_total, error_total=excluded.error_total,
                       ats_result=excluded.ats_result, ou_result=excluded.ou_result, confidence=excluded.confidence,
                       graded_spread=excluded.graded_spread, edge_points=excluded.edge_points,
                       pooled_fcs=excluded.pooled_fcs, generated_at=excluded.generated_at""",
                (g['game_id'], g['season'], g['week'], s['fair_home_spread'], closing_spread, error_spread,
                 s['projected_total'], closing_total, error_total, ats, ou, s['confidence'],
                 graded, edge, pooled, s['generated_at']))
            n += 1
        con.commit()
    return n


if __name__ == '__main__':
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument('season', type=int)
    a = p.parse_args()
    print(f'Logged {log_season(a.season)} games')
