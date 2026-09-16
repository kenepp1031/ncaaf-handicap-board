"""Overall ATS/O-U record + MAE, and a per-adjustment breakdown (whether each
prior/adjustment actually helps spread accuracy where it fires)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from db.db import connect


def overall_record(season: int | None = None) -> dict:
    query = 'SELECT * FROM backtest_log'
    params = ()
    if season is not None:
        query += ' WHERE season=?'
        params = (season,)
    with connect() as con:
        rows = con.execute(query, params).fetchall()
    ats = [r['ats_result'] for r in rows if r['ats_result']]
    ou = [r['ou_result'] for r in rows if r['ou_result']]
    spread_errors = [abs(r['error_spread']) for r in rows if r['error_spread'] is not None]
    total_errors = [abs(r['error_total']) for r in rows if r['error_total'] is not None]
    return {
        'games': len(rows),
        'ats_wins': ats.count('win'), 'ats_losses': ats.count('loss'), 'ats_pushes': ats.count('push'),
        'ou_wins': ou.count('win'), 'ou_losses': ou.count('loss'), 'ou_pushes': ou.count('push'),
        'spread_mae': round(sum(spread_errors) / len(spread_errors), 3) if spread_errors else None,
        'total_mae': round(sum(total_errors) / len(total_errors), 3) if total_errors else None,
    }


def per_adjustment_breakdown(season: int | None = None) -> dict:
    """Spread MAE on games where each prior fired (non-zero) vs. didn't."""
    query = """SELECT g.game_id, b.error_spread, p.spend_margin_shift, p.officiating_margin_shift, p.talent_margin_shift
               FROM backtest_log b JOIN games g ON g.game_id=b.game_id JOIN projections p ON p.game_id=b.game_id"""
    params = ()
    if season is not None:
        query += ' WHERE g.season=?'
        params = (season,)
    with connect() as con:
        rows = con.execute(query, params).fetchall()
    out = {}
    for field in ('spend_margin_shift', 'officiating_margin_shift', 'talent_margin_shift'):
        fired = [abs(r['error_spread']) for r in rows if r[field] and abs(r[field]) > 0.01 and r['error_spread'] is not None]
        idle = [abs(r['error_spread']) for r in rows if (not r[field] or abs(r[field]) <= 0.01) and r['error_spread'] is not None]
        out[field] = {
            'fired_n': len(fired), 'fired_mae': round(sum(fired) / len(fired), 3) if fired else None,
            'idle_n': len(idle), 'idle_mae': round(sum(idle) / len(idle), 3) if idle else None,
        }
    return out


if __name__ == '__main__':
    import argparse
    import json
    p = argparse.ArgumentParser()
    p.add_argument('--season', type=int)
    a = p.parse_args()
    print(json.dumps({'overall': overall_record(a.season), 'by_adjustment': per_adjustment_breakdown(a.season)}, indent=2))
