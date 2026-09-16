"""One-time migration: import the live server's existing market_lines closing-
line captures and locations.json geocode cache into the new SQLite schema.
Run once after Phase 1's schema exists, before deleting data/picks.sqlite3
and data/locations.json. Safe to re-run (upserts).
"""
from __future__ import annotations

import json
import sys
import sqlite3
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from db.db import connect, init_db

DATA = Path(__file__).resolve().parent / 'data'


def migrate_market_lines():
    path = DATA / 'picks.sqlite3'
    if not path.exists():
        print('No data/picks.sqlite3 found; skipping market_lines migration.')
        return 0
    src = sqlite3.connect(path)
    src.row_factory = sqlite3.Row
    try:
        rows = src.execute('SELECT * FROM market_lines').fetchall()
    except sqlite3.OperationalError:
        print('No market_lines table in data/picks.sqlite3; skipping.')
        return 0
    finally:
        pass
    n = 0
    with connect() as con:
        for r in rows:
            con.execute(
                """INSERT OR IGNORE INTO line_history (game_id, captured_at, kickoff, home_spread, total, home_odds, away_odds, source)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (r['event_id'], r['captured_at'], r['kickoff'], r['home_spread'], r['total'],
                 r['home_odds'], r['away_odds'], r['source']))
            n += 1
        con.commit()
    src.close()
    return n


def migrate_locations():
    path = DATA / 'locations.json'
    if not path.exists():
        print('No data/locations.json found; skipping geocode migration.')
        return 0
    locations = json.loads(path.read_text(encoding='utf-8'))
    n = 0
    with connect() as con:
        for key, coords in locations.items():
            parts = key.split('|')
            if len(parts) != 3:
                continue
            city, state, country = parts
            con.execute(
                """INSERT INTO geocode_cache (city, state, country, latitude, longitude, admin1, country_code)
                   VALUES (?,?,?,?,?,?,?)
                   ON CONFLICT(city, state, country) DO UPDATE SET
                       latitude=excluded.latitude, longitude=excluded.longitude,
                       admin1=excluded.admin1, country_code=excluded.country_code""",
                (city, state, country, coords.get('latitude'), coords.get('longitude'),
                 coords.get('admin1'), coords.get('country_code')))
            n += 1
        con.commit()
    return n


if __name__ == '__main__':
    init_db()
    n1 = migrate_market_lines()
    n2 = migrate_locations()
    print(f'Migrated {n1} closing-line captures and {n2} geocoded cities.')
