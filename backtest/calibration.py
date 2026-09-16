"""Bucket graded picks by qualitative confidence and report actual ATS win%
per bucket — checks whether "Low/Moderate/High" tracks real predictive power.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from db.db import connect

BUCKETS = ('Low', 'Moderate', 'High')


def calibration_report(season: int | None = None) -> dict:
    query = 'SELECT confidence, ats_result FROM backtest_log WHERE ats_result IS NOT NULL'
    params = ()
    if season is not None:
        query += ' AND season=?'
        params = (season,)
    with connect() as con:
        rows = con.execute(query, params).fetchall()
    report = {}
    for bucket in BUCKETS:
        picks = [r for r in rows if r['confidence'] == bucket and r['ats_result'] != 'push']
        wins = sum(1 for r in picks if r['ats_result'] == 'win')
        n = len(picks)
        report[bucket] = {'n': n, 'wins': wins, 'win_pct': round(wins / n, 4) if n else None}
    return report


if __name__ == '__main__':
    import argparse
    import json
    p = argparse.ArgumentParser()
    p.add_argument('--season', type=int)
    a = p.parse_args()
    print(json.dumps(calibration_report(a.season), indent=2))
