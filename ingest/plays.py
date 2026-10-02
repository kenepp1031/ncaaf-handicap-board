"""Per-play efficiency ingest (ESPN game summary -> drives -> plays).

The same summary endpoint box_scores.py reads also carries every drive and
every play with down, distance and yards. This folds them into per-team
success rate, explosiveness and garbage-time-free yards per play. A finished
game's plays never change, so only misses are fetched (permanent cache).
"""
from __future__ import annotations

import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common import ESPN, fetch_json
from db.db import connect

SUMMARY = ESPN + 'summary?event={}'
FETCH_BUDGET_SECONDS = 60
FETCH_WORKERS = 6
MIN_PLAYS = 40          # a side with fewer scrimmage plays than this is a broken feed, not a game

# Garbage time (Connelly): a lead this big in this quarter means the rest is noise.
GARBAGE_LEAD = {2: 38, 3: 28, 4: 22}
EXPLOSIVE_RUSH = 12
EXPLOSIVE_PASS = 16

_RUSH = ('rush', 'rushing touchdown')
_PASS = ('pass reception', 'pass incompletion', 'passing touchdown', 'pass interception return',
         'interception return touchdown', 'sack', 'pass')
_TURNOVER = ('interception', 'fumble recovery (opponent)', 'fumble return touchdown', 'interception return touchdown')


def _kind(play_type: str):
    t = (play_type or '').lower()
    if t in _RUSH or t.startswith('rush'):
        return 'rush'
    if t in _PASS or t.startswith('pass') or t == 'sack':
        return 'pass'
    if 'fumble' in t:
        return 'rush'          # a fumble on a scrimmage play; ESPN does not say which kind, rush is the common case
    return None                # kickoff, punt, field goal, penalty, timeout, end of period, etc.


def _success(down, distance, yards, scoring):
    if scoring:
        return True
    if down == 1:
        return yards >= 0.5 * distance
    if down == 2:
        return yards >= 0.7 * distance
    return yards >= distance


def _garbage(period, offense_score, defense_score):
    lead = abs(offense_score - defense_score)
    limit = GARBAGE_LEAD.get(period)
    return limit is not None and lead > limit


def _blank(team_id, side):
    return {'side': side, 'team_id': team_id, 'plays': 0, 'yards': 0, 'successes': 0, 'explosives': 0, 'turnovers': 0,
            'rush_plays': 0, 'rush_yards': 0, 'rush_successes': 0, 'pass_plays': 0, 'pass_yards': 0, 'pass_successes': 0,
            'plays_ng': 0, 'yards_ng': 0, 'successes_ng': 0, 'explosives_ng': 0, 'turnovers_ng': 0,
            'drives': 0, 'drive_points': 0}


def _extract(summary: dict):
    comp = summary.get('header', {}).get('competitions', [{}])[0]
    sides = {}
    for c in comp.get('competitors', []):
        sides[str(c['team']['id'])] = c.get('homeAway')
    if len(sides) != 2:
        return None
    rows = {tid: _blank(tid, side) for tid, side in sides.items()}
    drives = summary.get('drives', {}).get('previous', [])
    if not drives:
        return None
    for d in drives:
        off = str(d.get('team', {}).get('id') or '')
        if off in rows:
            rows[off]['drives'] += 1
            result = (d.get('displayResult') or d.get('result') or '').upper()
            if result in ('TD', 'TOUCHDOWN', 'RUSHING TD', 'PASSING TD'):
                rows[off]['drive_points'] += 7
            elif result in ('FG', 'FIELD GOAL', 'MADE FG'):
                rows[off]['drive_points'] += 3
        for p in d.get('plays', []):
            kind = _kind(p.get('type', {}).get('text'))
            start = p.get('start') or {}
            tid = str((start.get('team') or {}).get('id') or off)
            if kind is None or tid not in rows or not start.get('down'):
                continue
            down, dist = int(start['down']), int(start.get('distance') or 0)
            yards = int(p.get('statYardage') or 0)
            scoring = bool(p.get('scoringPlay')) and not p.get('isTurnover')
            if scoring and 'touchdown' in (p.get('type', {}).get('text') or '').lower() and tid != off:
                scoring = False      # defensive score: not an offensive success for the possession team
            succ = _success(down, dist, yards, scoring)
            expl = yards >= (EXPLOSIVE_RUSH if kind == 'rush' else EXPLOSIVE_PASS)
            to = bool(p.get('isTurnover'))
            r = rows[tid]
            r['plays'] += 1; r['yards'] += yards; r['successes'] += succ; r['explosives'] += expl; r['turnovers'] += to
            r[f'{kind}_plays'] += 1; r[f'{kind}_yards'] += yards; r[f'{kind}_successes'] += succ
            # garbage time is judged from the score at the snap, from the offense's point of view
            home_s, away_s = int(p.get('homeScore') or 0), int(p.get('awayScore') or 0)
            mine, theirs = (home_s, away_s) if sides[tid] == 'home' else (away_s, home_s)
            if not _garbage(int(p.get('period', {}).get('number') or 0), mine, theirs):
                r['plays_ng'] += 1; r['yards_ng'] += yards; r['successes_ng'] += succ
                r['explosives_ng'] += expl; r['turnovers_ng'] += to
    out = list(rows.values())
    if any(r['plays'] < MIN_PLAYS for r in out):
        return None
    return out


def ingest(budget_seconds: float = FETCH_BUDGET_SECONDS) -> dict:
    now = datetime.now().astimezone().isoformat(timespec='seconds')
    with connect() as con:
        have = {r['game_id'] for r in con.execute('SELECT DISTINCT game_id FROM play_stats')}
        missing = [r['game_id'] for r in con.execute('SELECT game_id FROM games WHERE completed=1 ORDER BY game_date DESC')
                   if r['game_id'] not in have]
    if not missing:
        return {'fetched': 0, 'failures': 0, 'remaining': 0}

    deadline = time.monotonic() + budget_seconds
    fetched, failures = 0, 0

    def pull(game_id):
        try:
            return game_id, _extract(fetch_json(SUMMARY.format(game_id)))
        except Exception:
            return game_id, None

    cols = ['plays', 'yards', 'successes', 'explosives', 'turnovers', 'rush_plays', 'rush_yards', 'rush_successes',
            'pass_plays', 'pass_yards', 'pass_successes', 'plays_ng', 'yards_ng', 'successes_ng', 'explosives_ng',
            'turnovers_ng', 'drives', 'drive_points']
    sql = (f"INSERT INTO play_stats (game_id, side, team_id, {', '.join(cols)}, captured_at) "
           f"VALUES ({', '.join('?' for _ in range(len(cols) + 4))}) ON CONFLICT(game_id, side) DO NOTHING")
    with connect() as con:
        with ThreadPoolExecutor(max_workers=FETCH_WORKERS) as pool:
            for game_id, rows in pool.map(pull, missing):
                if rows:
                    for r in rows:
                        con.execute(sql, (game_id, r['side'], r['team_id'], *[r[c] for c in cols], now))
                    fetched += 1
                else:
                    failures += 1
                if time.monotonic() >= deadline:
                    break
        con.commit()
    return {'fetched': fetched, 'failures': failures, 'remaining': max(0, len(missing) - fetched - failures)}


if __name__ == '__main__':
    import argparse
    from db.db import init_db
    p = argparse.ArgumentParser()
    p.add_argument('--budget', type=float, default=FETCH_BUDGET_SECONDS, help='Seconds to spend fetching (backfill: use a large value)')
    a = p.parse_args()
    init_db()
    print(ingest(a.budget))
