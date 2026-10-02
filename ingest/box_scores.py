"""Team box-score ingest (ESPN game summary): plays, yards, turnovers, starting QB.

Same endpoint and permanent-cache pattern as ingest/officiating.py: a finished
game's box score never changes, so this only fetches games the `box_scores`
table doesn't already have.
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


def _int(value):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _pair(value, sep):
    parts = str(value or '').split(sep, 1)
    return (_int(parts[0]), _int(parts[1])) if len(parts) == 2 else (None, None)


def _seconds(clock):
    minutes, seconds = _pair(clock, ':')
    return None if minutes is None or seconds is None else minutes * 60 + seconds


def _starting_qb(players_block):
    passing = next((s for s in players_block.get('statistics', []) if s.get('name') == 'passing'), None)
    if not passing:
        return None, None, None
    best = None
    for a in passing.get('athletes', []):
        attempts = _pair(a.get('stats', [''])[0], '/')[1]
        if attempts is not None and (best is None or attempts > best[2]):
            best = (str(a['athlete']['id']), a['athlete'].get('displayName'), attempts)
    return best or (None, None, None)


def _extract(summary: dict):
    box = summary.get('boxscore', {})
    players = {str(p['team']['id']): p for p in box.get('players', [])}
    rows = []
    for t in box.get('teams', []):
        stats = {s.get('name'): s.get('displayValue') for s in t.get('statistics', [])}
        if stats.get('totalYards') is None:
            return None
        pass_att = _pair(stats.get('completionAttempts'), '/')[1]
        rush_att = _int(stats.get('rushingAttempts'))
        third_conv, third_att = _pair(stats.get('thirdDownEff'), '-')
        team_id = str(t['team']['id'])
        qb_id, qb_name, qb_attempts = _starting_qb(players.get(team_id, {}))
        rows.append({'side': t['homeAway'], 'team_id': team_id,
                     'plays': None if pass_att is None or rush_att is None else pass_att + rush_att,
                     'total_yards': _int(stats.get('totalYards')), 'pass_attempts': pass_att, 'rush_attempts': rush_att,
                     'first_downs': _int(stats.get('firstDowns')), 'third_down_conv': third_conv, 'third_down_att': third_att,
                     'turnovers': _int(stats.get('turnovers')), 'possession_seconds': _seconds(stats.get('possessionTime')),
                     'qb_id': qb_id, 'qb_name': qb_name, 'qb_attempts': qb_attempts})
    return rows if len(rows) == 2 else None


def ingest(budget_seconds: float = FETCH_BUDGET_SECONDS) -> dict:
    now = datetime.now().astimezone().isoformat(timespec='seconds')
    with connect() as con:
        have = {r['game_id'] for r in con.execute('SELECT DISTINCT game_id FROM box_scores')}
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

    with connect() as con:
        with ThreadPoolExecutor(max_workers=FETCH_WORKERS) as pool:
            for game_id, rows in pool.map(pull, missing):
                if rows:
                    for r in rows:
                        con.execute(
                            """INSERT INTO box_scores (game_id, side, team_id, plays, total_yards, pass_attempts,
                                    rush_attempts, first_downs, third_down_conv, third_down_att, turnovers,
                                    possession_seconds, qb_id, qb_name, qb_attempts, captured_at)
                               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                               ON CONFLICT(game_id, side) DO NOTHING""",
                            (game_id, r['side'], r['team_id'], r['plays'], r['total_yards'], r['pass_attempts'],
                             r['rush_attempts'], r['first_downs'], r['third_down_conv'], r['third_down_att'],
                             r['turnovers'], r['possession_seconds'], r['qb_id'], r['qb_name'], r['qb_attempts'], now))
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
