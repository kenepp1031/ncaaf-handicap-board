"""The "Sharp side" list: games where DraftKings' money share beats its ticket share
by SHARP_GAP points or more on one side.

Measured 2026-10-02 on 82 completed 2026 games: that side went 47-34 ATS (58%) and
won outright 60%, on lines that averaged pick'em. Line moves of 1.5+ points covered
61%, reverse line moves 62% (but as big dogs). The model's own lean went 47.5%.
Small samples, so this logs every qualifying game from the first run it qualifies,
with the line on the board at that moment, and grades itself as games finish. In
eight weeks the record says whether it pays.

A row is written once and never deleted. If the gap later closes, still_qualifies
drops to 0 but the pick stays in the record, because it was a pick when you saw it.
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common import normal
from db.db import connect

SHARP_GAP = 10.0          # money share minus ticket share, percentage points
MODEL_EDGE = 1.0          # model lean counts as agreeing at 1+ pt vs the market
MOVE_FLAG = 1.5           # a line move this big toward the side is called out on the card


def _side_splits(con, games):
    """{game_id: {'home': (handle, bets, spread), 'away': (...)}} from the latest DK capture."""
    out = {}
    for r in con.execute('SELECT * FROM splits WHERE game_id IS NOT NULL'):
        g = games.get(r['game_id'])
        if not g:
            continue
        key = normal(r['team_key'])
        side = 'home' if key == normal(g['hn']) else ('away' if key == normal(g['an']) else None)
        if side:
            out.setdefault(r['game_id'], {})[side] = (r['handle_pct'], r['bets_pct'], r['spread'])
    return out


def _line_moves(con, games):
    """{game_id: (opening home spread, latest pre-kickoff home spread)}"""
    seq = {}
    for r in con.execute('SELECT game_id, captured_at, home_spread FROM line_history WHERE home_spread IS NOT NULL ORDER BY captured_at'):
        g = games.get(r['game_id'])
        if g and r['captured_at'] < g['kickoff']:
            seq.setdefault(r['game_id'], []).append(r['home_spread'])
    return {gid: (s[0], s[-1]) for gid, s in seq.items()}


def _model_sides(con):
    out = {}
    for r in con.execute('SELECT p.game_id, p.lean_home_spread, p.fair_home_spread, g.home_spread FROM projections p JOIN games g USING(game_id)'):
        m = r['lean_home_spread'] if r['lean_home_spread'] is not None else r['fair_home_spread']
        if m is None or r['home_spread'] is None:
            continue
        e = r['home_spread'] - m
        if abs(e) >= MODEL_EDGE:
            out[r['game_id']] = 'home' if e > 0 else 'away'
    return out


def update(season: int) -> dict:
    """Log newly qualifying sides for games that have not kicked off, refresh the
    display fields on existing rows, and grade finished games."""
    now = datetime.now().astimezone().isoformat(timespec='seconds')
    with connect() as con:
        games = {g['game_id']: dict(g) for g in con.execute(
            """SELECT g.*, th.name hn, ta.name an FROM games g
               JOIN teams th ON th.team_id=g.home_id JOIN teams ta ON ta.team_id=g.away_id WHERE g.season=?""", (season,))}
        splits = _side_splits(con, games)
        moves = _line_moves(con, games)
        model = _model_sides(con)
        existing = {(r['game_id'], r['side']): dict(r) for r in con.execute('SELECT * FROM sharp_picks WHERE season=?', (season,))}
        added = 0
        for gid, sides in splits.items():
            g = games[gid]
            if g['completed'] or now >= g['kickoff']:
                continue
            for side, (handle, bets, spread) in sides.items():
                if handle is None or bets is None:
                    continue
                gap = handle - bets
                qualifies = gap >= SHARP_GAP
                row = existing.get((gid, side))
                if row:
                    con.execute('UPDATE sharp_picks SET last_handle_pct=?, last_bets_pct=?, still_qualifies=? WHERE game_id=? AND side=?',
                                (handle, bets, 1 if qualifies else 0, gid, side))
                    continue
                if not qualifies:
                    continue
                home_spread = g['home_spread'] if g['home_spread'] is not None else (spread if side == 'home' else (None if spread is None else -spread))
                side_spread = None if home_spread is None else (home_spread if side == 'home' else -home_spread)
                opening, latest = moves.get(gid, (None, None))
                move = None if opening is None else round((opening - latest) * (1 if side == 'home' else -1), 2)
                con.execute(
                    """INSERT INTO sharp_picks (game_id, side, season, week, first_seen, spread_at_pick, handle_pct, bets_pct, gap,
                            line_move, model_agrees, last_handle_pct, last_bets_pct, still_qualifies)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,1)""",
                    (gid, side, season, g['week'], now, side_spread, handle, bets, round(gap, 1), move,
                     1 if model.get(gid) == side else 0, handle, bets))
                added += 1
        graded = _grade(con, games, moves)
        con.commit()
    return {'added': added, 'graded': graded}


def _grade(con, games, moves):
    n = 0
    for r in con.execute('SELECT * FROM sharp_picks WHERE su_result IS NULL').fetchall():
        g = games.get(r['game_id'])
        if not g or not g['completed'] or g['home_score'] is None:
            continue
        margin = g['home_score'] - g['away_score']
        close_home = moves.get(r['game_id'], (None, g['home_spread']))[1]
        if close_home is None:
            close_home = g['home_spread']
        sign = 1 if r['side'] == 'home' else -1
        close_side = None if close_home is None else close_home * sign

        def ats(side_spread):
            if side_spread is None:
                return None
            cov = margin * sign + side_spread
            return 'push' if cov == 0 else ('win' if cov > 0 else 'loss')
        su = 'win' if margin * sign > 0 else ('loss' if margin * sign < 0 else 'push')
        con.execute('UPDATE sharp_picks SET closing_spread=?, ats_result=?, ats_result_at_pick=?, su_result=? WHERE game_id=? AND side=?',
                    (close_side, ats(close_side), ats(r['spread_at_pick']), su, r['game_id'], r['side']))
        n += 1
    return n


def record(con, season: int) -> dict:
    rows = [dict(r) for r in con.execute('SELECT * FROM sharp_picks WHERE season=? AND su_result IS NOT NULL', (season,))]

    def rec(key):
        vals = [r[key] for r in rows if r[key]]
        return f"{vals.count('win')}-{vals.count('loss')}" + (f"-{vals.count('push')}" if vals.count('push') else '')
    return {'graded': len(rows), 'ats': rec('ats_result'), 'ats_at_pick': rec('ats_result_at_pick'), 'su': rec('su_result'),
            'su_pct': round(100 * sum(r['su_result'] == 'win' for r in rows) / len(rows)) if rows else None}


def this_week(con, season: int, week: int) -> list[dict]:
    return [dict(r) for r in con.execute(
        """SELECT s.*, g.kickoff, g.home_spread, g.completed, g.home_score, g.away_score, g.home_id, g.away_id,
                  th.name hn, ta.name an FROM sharp_picks s JOIN games g USING(game_id)
           JOIN teams th ON th.team_id=g.home_id JOIN teams ta ON ta.team_id=g.away_id
           WHERE s.season=? AND s.week=? ORDER BY g.kickoff""", (season, week))]


if __name__ == '__main__':
    import argparse
    import json
    p = argparse.ArgumentParser()
    p.add_argument('season', type=int)
    a = p.parse_args()
    print(update(a.season))
    with connect() as con:
        print(json.dumps(record(con, a.season)))
        for r in con.execute('SELECT s.week, th.name, ta.name, s.side, s.spread_at_pick, s.gap, s.line_move, s.model_agrees, s.su_result, s.ats_result FROM sharp_picks s JOIN games g USING(game_id) JOIN teams th ON th.team_id=g.home_id JOIN teams ta ON ta.team_id=g.away_id WHERE s.season=? ORDER BY g.kickoff', (a.season,)):
            print('  ', tuple(r))
