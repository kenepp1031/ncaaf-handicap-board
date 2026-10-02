"""Hand adjustments to team strength, read from manual_adjustments.csv in the
project root every run.

One row per team you want to nudge:

    team,points,note,until
    Ohio State,1.5,Looked better than the score vs Penn State,
    Texas,-4,Starting QB out (ankle),2026-10-20

* `team`      school name as the dashboard prints it (matching ignores case,
              spaces and punctuation; "Miami (FL)" and "miami fl" both work)
* `points`    points of margin added to that team in every game it plays.
              Positive = you think it is better than the model says.
              A starting QB out is typically -4 to -7; "a hair" is 0.5 to 1.5.
* `note`      why, shown on the dashboard next to the adjustment
* `until`     optional YYYY-MM-DD; the row stops applying after that date.
              Leave blank for the rest of the season.

Lines starting with # are ignored. Every run logs the names it could not match.

The adjustment is applied to the projected margin AFTER the model and the
priors, and it is stored separately in projections, projection_snapshots and
backtest_log so the record can be read with and without your hand on it
(backtest/report.py -> "your_hand").
"""
from __future__ import annotations

import csv
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common import normal

PATH = Path(__file__).resolve().parent.parent / 'manual_adjustments.csv'
MAX_POINTS = 10.0   # a typo like 15 instead of 1.5 should not move a line by two touchdowns


def load(as_of: date | None = None, names: dict | None = None) -> dict:
    """Return {'by_team': {team_id: {'points', 'note', 'name'}}, 'unmatched': [...], 'rows': n}.

    `names` is {team_id: name}; without it the adjustments are keyed by the
    normalized name instead of the team id.
    """
    as_of = as_of or date.today()
    out = {'by_team': {}, 'unmatched': [], 'rows': 0, 'expired': 0}
    if not PATH.exists():
        return out
    key_to_id = {}
    for tid, name in (names or {}).items():
        key_to_id.setdefault(normal(name), tid)
    with open(PATH, newline='', encoding='utf-8-sig') as f:
        for row in csv.DictReader(_strip_comments(f)):
            team = (row.get('team') or '').strip()
            if not team:
                continue
            out['rows'] += 1
            try:
                points = float((row.get('points') or '0').strip() or 0)
            except ValueError:
                out['unmatched'].append(f'{team} (points not a number)')
                continue
            until = (row.get('until') or '').strip()
            if until:
                try:
                    if date.fromisoformat(until) < as_of:
                        out['expired'] += 1
                        continue
                except ValueError:
                    out['unmatched'].append(f'{team} (bad until date {until!r})')
                    continue
            points = max(-MAX_POINTS, min(MAX_POINTS, points))
            key = normal(team)
            tid = key_to_id.get(key, key if not names else None)
            if tid is None:
                out['unmatched'].append(team)
                continue
            prev = out['by_team'].get(tid)
            out['by_team'][tid] = {'points': round((prev['points'] if prev else 0.0) + points, 2),
                                   'note': (row.get('note') or '').strip() or (prev['note'] if prev else ''),
                                   'name': team}
    return out


def _strip_comments(lines):
    for line in lines:
        if not line.lstrip().startswith('#'):
            yield line


def margin_shift(adjustments: dict, home_id, away_id) -> float:
    """Points added to the HOME margin: home nudge minus away nudge."""
    by = adjustments.get('by_team', {}) if adjustments else {}
    h = by.get(home_id, {}).get('points', 0.0)
    a = by.get(away_id, {}).get('points', 0.0)
    return round(h - a, 2)


if __name__ == '__main__':
    from db.db import connect
    with connect() as con:
        names = {r['team_id']: r['name'] for r in con.execute('SELECT team_id, name FROM teams')}
    loaded = load(names=names)
    print(f"{loaded['rows']} rows, {len(loaded['by_team'])} teams nudged, {loaded['expired']} expired")
    for tid, a in sorted(loaded['by_team'].items(), key=lambda kv: -abs(kv[1]['points'])):
        print(f"  {names.get(tid, tid):28s} {a['points']:+.1f}  {a['note']}")
    for u in loaded['unmatched']:
        print(f'  UNMATCHED: {u}')
