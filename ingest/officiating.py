"""Team-level penalty-tendency ingest (ESPN box scores).

Ported from officiating.py's fetch half. The fit/margin_shift half (a pure
function of ratings) lives in ratings/officiating_prior.py. Permanent cache:
a finished game's penalty count never changes, so this only fetches games
the `officiating_penalties` table doesn't already have.
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
FETCH_BUDGET_SECONDS = 40
FETCH_WORKERS = 6


def _extract(summary: dict):
    stats = {s['homeAway']: s['statistics'] for s in summary.get('boxscore', {}).get('teams', [])}

    def penalties(side):
        row = next((s for s in stats.get(side, []) if s.get('name') == 'totalPenaltiesYards'), None)
        if not row or '-' not in str(row.get('displayValue', '')):
            return None, None
        count, yards = row['displayValue'].split('-', 1)
        try:
            return int(count), int(yards)
        except ValueError:
            return None, None

    home_count, home_yards = penalties('home')
    away_count, away_yards = penalties('away')
    if home_count is None or away_count is None:
        return None
    return home_count, home_yards, away_count, away_yards


def ingest(budget_seconds: float = FETCH_BUDGET_SECONDS) -> dict:
    now = datetime.now().astimezone().isoformat(timespec='seconds')
    with connect() as con:
        have = {r['game_id'] for r in con.execute('SELECT game_id FROM officiating_penalties')}
        missing = [r['game_id'] for r in con.execute('SELECT game_id FROM games WHERE completed=1')
                   if r['game_id'] not in have]
    if not missing:
        return {'fetched': 0, 'failures': 0}

    deadline = time.monotonic() + budget_seconds
    fetched, failures = 0, 0

    def pull(game_id):
        return game_id, _extract(fetch_json(SUMMARY.format(game_id)))

    with connect() as con:
        with ThreadPoolExecutor(max_workers=FETCH_WORKERS) as pool:
            for game_id, result in pool.map(pull, missing):
                if result:
                    hc, hy, ac, ay = result
                    con.execute(
                        """INSERT INTO officiating_penalties (game_id, home_penalties, home_penalty_yards,
                                away_penalties, away_penalty_yards, captured_at) VALUES (?,?,?,?,?,?)
                           ON CONFLICT(game_id) DO UPDATE SET
                               home_penalties=excluded.home_penalties, home_penalty_yards=excluded.home_penalty_yards,
                               away_penalties=excluded.away_penalties, away_penalty_yards=excluded.away_penalty_yards,
                               captured_at=excluded.captured_at""",
                        (game_id, hc, hy, ac, ay, now))
                    fetched += 1
                else:
                    failures += 1
                if time.monotonic() >= deadline:
                    break
        con.commit()
    return {'fetched': fetched, 'failures': failures}


if __name__ == '__main__':
    print(ingest())
