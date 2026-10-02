"""Starting-quarterback injury prior.

The one injury that reliably moves a college line is the starting QB. This
joins covers.com's injury list (ingest/injuries.py) to the starter the box
scores say each team actually uses (most pass attempts, most starts this
season) and takes points off a team whose starter is listed Out or Doubtful.

Points are a prior, not a measurement: the local record is far too small to
fit them. QB_OUT_POINTS is the conventional 4 (books move 4-7 for a real
starter; 4 is the conservative end). The shift is stored on its own in
projections / projection_snapshots / backtest_log, so report.py can grade
the games it touched with and without it, and the number can be tuned once
there is a sample.

If the backup has already started the team's most recent game, the model has
seen a little of life without the starter, so the shift is halved.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common import normal
from db.db import connect

HORIZON_DAYS = 8        # an injury listed today says nothing about a game a month out
QB_OUT_POINTS = 4.0
QB_DOUBTFUL_POINTS = 2.0
STATUS_POINTS = {'out': QB_OUT_POINTS, 'doubtful': QB_DOUBTFUL_POINTS, 'injured reserve': QB_OUT_POINTS,
                 'out for season': QB_OUT_POINTS, 'suspended': QB_OUT_POINTS}
NOTE_STATUSES = {'questionable', 'day-to-day', 'probable', 'game time decision'}
MIN_STARTS = 1


def _initial_last(name: str):
    """('c', 'ballard') for both 'C. Ballard' and 'Cole Ballard'. Suffixes kept, so
    'A. Barnett III' matches 'Avery Barnett III'."""
    parts = (name or '').replace('.', ' ').split()
    if len(parts) < 2:
        return None
    return parts[0][0].lower(), normal(' '.join(parts[1:]))


def starters(con, season: int, before_date: str | None = None) -> dict:
    """{team_id: {'qb_id','qb_name','starts','games','last_qb_id','last_qb_name'}} from
    this season's box scores (games before `before_date` if given)."""
    rows = con.execute(
        """SELECT b.team_id, b.qb_id, b.qb_name, g.game_date FROM box_scores b JOIN games g USING(game_id)
           WHERE g.season=? AND g.completed=1 AND b.qb_id IS NOT NULL ORDER BY g.game_date""", (season,)).fetchall()
    log = {}
    for r in rows:
        if before_date and r['game_date'] >= before_date:
            continue
        log.setdefault(r['team_id'], []).append(r)
    out = {}
    for tid, games in log.items():
        counts = {}
        for r in games:
            counts[r['qb_id']] = counts.get(r['qb_id'], 0) + 1
        primary = max(counts, key=lambda q: (counts[q], max(i for i, r in enumerate(games) if r['qb_id'] == q)))
        name = next(r['qb_name'] for r in games if r['qb_id'] == primary)
        out[tid] = {'qb_id': primary, 'qb_name': name, 'starts': counts[primary], 'games': len(games),
                    'last_qb_id': games[-1]['qb_id'], 'last_qb_name': games[-1]['qb_name']}
    return out


def load(season: int) -> dict:
    """{team_id: {'points', 'note', 'status', 'player', 'injury', 'reported', 'severity'}} for every
    FBS team whose listed starter is hurt. severity: 'out' (points applied) or 'watch' (note only)."""
    with connect() as con:
        starts = starters(con, season)
        listed = [dict(r) for r in con.execute("SELECT * FROM injuries WHERE pos='QB'")]
    out = {}
    for inj in listed:
        s = starts.get(inj['team_id'])
        if not s or s['starts'] < MIN_STARTS:
            continue
        if _initial_last(inj['player']) != _initial_last(s['qb_name']):
            continue
        status = (inj['status'] or '').strip().lower()
        points = STATUS_POINTS.get(status)
        if points is None and status not in NOTE_STATUSES:
            continue
        backup_started = s['last_qb_id'] != s['qb_id']
        if points and backup_started:
            points = round(points / 2, 2)
        why = inj['injury'] or 'injury'
        when = f", listed {inj['reported']}" if inj['reported'] else ''
        if points:
            note = (f"QB out: {s['qb_name']} ({inj['status']}, {why}{when}) started {s['starts']} of {s['games']} games"
                    + (f"; {s['last_qb_name']} started last game" if backup_started else ''))
        else:
            note = f"QB {inj['status'].lower()}: {s['qb_name']} ({why}{when}) started {s['starts']} of {s['games']} games"
        out[inj['team_id']] = {'points': points or 0.0, 'note': note, 'status': inj['status'], 'player': s['qb_name'],
                               'injury': inj['injury'], 'reported': inj['reported'],
                               'severity': 'out' if points else 'watch'}
    return out


def in_horizon(game_date: str, as_of) -> bool:
    from datetime import date
    try:
        delta = (date.fromisoformat(game_date) - as_of).days
    except (TypeError, ValueError):
        return False
    return 0 <= delta <= HORIZON_DAYS


def team_note(prior: dict, team_id) -> str | None:
    hit = (prior or {}).get(team_id)
    return hit['note'] if hit else None


def margin_shift(prior: dict, home_id, away_id) -> float:
    """Points added to the HOME margin. A home QB out lowers it; an away QB out raises it."""
    by = prior or {}
    return round(-by.get(home_id, {}).get('points', 0.0) + by.get(away_id, {}).get('points', 0.0), 2)


if __name__ == '__main__':
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument('season', type=int)
    a = p.parse_args()
    with connect() as con:
        names = {r['team_id']: r['name'] for r in con.execute('SELECT team_id, name FROM teams')}
    hits = load(a.season)
    print(f'{len(hits)} team(s) with a listed starting QB:')
    for tid, h in sorted(hits.items(), key=lambda kv: -kv[1]['points']):
        print(f"  {names.get(tid, tid):22s} {h['points']:+.1f}  {h['note']}")
