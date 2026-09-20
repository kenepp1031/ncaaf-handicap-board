"""Graded-record summary.

Headline accuracy covers FBS-vs-FBS games only. Games where a side resolved to
the pooled FCS rating are reported separately: they are unbettable 40-point
lines whose errors swamp everything else (one Oregon 84-0 Portland State
supplied 31.5 of the 44.2 total absolute error in the first version of this log).

The edge breakdown is the point of the whole file. Walk-forward over 2025-26 the
model's margin error rose monotonically with its distance from the closing line
-- 10.7 MAE inside a point, 17.9 at 10+ -- so a record that isn't split by edge
hides the only thing worth knowing.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from db.db import connect

EDGE_BUCKETS = [(0, 1), (1, 2), (2, 3), (3, 4), (4, 6), (6, 10), (10, 1e9)]


def _fetch(season=None, pooled=False):
    q = 'SELECT * FROM backtest_log WHERE pooled_fcs=?'
    params = [1 if pooled else 0]
    if season is not None:
        q += ' AND season=?'
        params.append(season)
    with connect() as con:
        return [dict(r) for r in con.execute(q, params)]


def _tally(rows):
    ats = [r['ats_result'] for r in rows if r['ats_result']]
    ou = [r['ou_result'] for r in rows if r['ou_result']]
    se = [abs(r['error_spread']) for r in rows if r['error_spread'] is not None]
    te = [abs(r['error_total']) for r in rows if r['error_total'] is not None]
    w, l = ats.count('win'), ats.count('loss')
    return {
        'games': len(rows),
        'ats': f"{w}-{l}-{ats.count('push')}",
        'ats_pct': round(100 * w / (w + l), 1) if w + l else None,
        'ou': f"{ou.count('win')}-{ou.count('loss')}-{ou.count('push')}",
        'spread_mae': round(sum(se) / len(se), 2) if se else None,
        'total_mae': round(sum(te) / len(te), 2) if te else None,
    }


def overall_record(season: int | None = None) -> dict:
    return _tally(_fetch(season, pooled=False))


def pooled_fcs_record(season: int | None = None) -> dict:
    return _tally(_fetch(season, pooled=True))


def by_edge(season: int | None = None) -> dict:
    rows = [r for r in _fetch(season, pooled=False) if r['edge_points'] is not None]
    out = {}
    for lo, hi in EDGE_BUCKETS:
        sel = [r for r in rows if lo <= abs(r['edge_points']) < hi]
        label = f'{lo:g}-{hi:g} pts' if hi < 1e9 else f'{lo:g}+ pts'
        out[label] = _tally(sel)
    return out


def by_confidence(season: int | None = None) -> dict:
    rows = _fetch(season, pooled=False)
    return {tier: _tally([r for r in rows if r['confidence'] == tier])
            for tier in ('High', 'Moderate', 'Low')}


def market_comparison(season: int | None = None) -> dict:
    """Model margin error vs. the closing line's own, on identical games.

    If the model isn't beating this, it has no edge no matter what the ATS
    record looks like over a short sample.
    """
    q = """SELECT b.error_spread, b.closing_spread, g.home_score, g.away_score
           FROM backtest_log b JOIN games g USING(game_id)
           WHERE b.pooled_fcs=0 AND b.error_spread IS NOT NULL AND b.closing_spread IS NOT NULL"""
    params = ()
    if season is not None:
        q += ' AND b.season=?'
        params = (season,)
    with connect() as con:
        rows = [dict(r) for r in con.execute(q, params)]
    if not rows:
        return {'games': 0, 'model_mae': None, 'market_mae': None, 'model_beats_market_by': None}
    model = [abs(r['error_spread']) for r in rows]
    market = [abs((-r['closing_spread']) - (r['home_score'] - r['away_score'])) for r in rows]
    mo, mk = sum(model) / len(model), sum(market) / len(market)
    return {'games': len(rows), 'model_mae': round(mo, 2), 'market_mae': round(mk, 2),
            'model_beats_market_by': round(mk - mo, 2)}


def per_adjustment_breakdown(season: int | None = None) -> dict:
    """Spread MAE on games where each prior fired (non-zero) vs. didn't."""
    query = """SELECT b.error_spread, p.spend_margin_shift, p.officiating_margin_shift, p.talent_margin_shift
               FROM backtest_log b JOIN games g ON g.game_id=b.game_id JOIN projections p ON p.game_id=b.game_id
               WHERE b.pooled_fcs=0"""
    params = ()
    if season is not None:
        query += ' AND g.season=?'
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
    print(json.dumps({
        'overall_fbs_only': overall_record(a.season),
        'vs_closing_line': market_comparison(a.season),
        'by_edge': by_edge(a.season),
        'by_confidence': by_confidence(a.season),
        'pooled_fcs_games': pooled_fcs_record(a.season),
        'by_adjustment': per_adjustment_breakdown(a.season),
    }, indent=2))
