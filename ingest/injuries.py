"""College football injury report (covers.com), one row per listed player.

ESPN's college injury feed is empty, so this scrapes covers.com's season page,
which lists every FBS team with player, position, status and date. The table
is a current snapshot (replaced each run); `injury_history` keeps every
capture so a game can later be judged on what was known before kickoff.
"""
from __future__ import annotations

import re
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common import clean, normal
from db.db import connect

SOURCE = 'https://www.covers.com/sport/football/ncaaf/injuries'
AGENT = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/128 Safari/537.36'}
MIN_TEAMS = 100

# covers.com spellings that common.normal() alone does not reach
ALIASES = {'miamifl': 'miami', 'miamiflorida': 'miami', 'ulmonroe': 'ulmonroe', 'louisianamonroe': 'ulmonroe',
           'southernmississippi': 'southernmiss', 'hawaii': 'hawaii', 'texasam': 'texasam', 'utsa': 'utsa',
           'louisianalafayette': 'louisiana', 'centralflorida': 'ucf', 'floridaintl': 'floridainternational',
           'sanjosest': 'sanjosestate', 'nevadalasvegas': 'unlv', 'brighamyoung': 'byu', 'southernmethodist': 'smu',
           'texaschristian': 'tcu', 'louisianastate': 'lsu', 'alabamabirmingham': 'uab', 'texasep': 'utep',
           'texaselpaso': 'utep', 'massachusetts': 'umass', 'connecticut': 'uconn'}


def key(name: str) -> str:
    k = normal(name)
    return ALIASES.get(k, k)


def _get(url=SOURCE):
    request = urllib.request.Request(url, headers=AGENT)
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read().decode('utf-8', 'replace')


def parse(page: str) -> list[dict]:
    """[{team, player, pos, status, injury, reported, note}] for every listed player."""
    out = []
    blocks = page.split('covers-CoversSeasonInjuries-blockContainer')[1:]
    for block in blocks:
        name = re.search(r'covers-CoversMatchups-teamName.*?<a[^>]*>\s*(.*?)<br>', block, re.S)
        if not name:
            continue
        team = clean(name[1])
        for row in re.finditer(r'<tr>\s*<td>\s*<span class=\'player-link\'>(.*?)</span>\s*</td>\s*<td>(.*?)</td>\s*'
                               r'<td><b>(.*?)</b>(.*?)</td>(.*?)</tr>', block, re.S):
            player, pos, status_text, when, rest = (clean(x) for x in row.groups())
            status, _, injury = (status_text.partition(' - '))
            note = re.search(r'injuryCopy">\s*(.*?)\s*</div>', block[row.end():row.end() + 3000], re.S)
            out.append({'team': team, 'player': player, 'pos': pos, 'status': status.strip(), 'injury': injury.strip() or None,
                        'reported': when.strip('() ').strip() or None, 'note': clean(note[1]) if note else None})
        if not re.search(r'player-link', block):
            out.append({'team': team, 'player': None, 'pos': None, 'status': None, 'injury': None, 'reported': None, 'note': None})
    return out


def _team_lookup(con):
    return {key(r['name']): r['team_id'] for r in con.execute('SELECT team_id, name FROM teams WHERE fbs=1')}


def ingest(get=_get) -> dict:
    now = datetime.now().astimezone().isoformat(timespec='seconds')
    rows = parse(get())
    teams_seen = {r['team'] for r in rows}
    if len(teams_seen) < MIN_TEAMS:
        raise ValueError(f'covers.com injuries page listed {len(teams_seen)} teams: layout changed')
    with connect() as con:
        lookup = _team_lookup(con)
        unmatched = sorted({r['team'] for r in rows if key(r['team']) not in lookup})
        con.execute('DELETE FROM injuries')
        kept = 0
        for r in rows:
            tid = lookup.get(key(r['team']))
            if not tid or not r['player']:
                continue
            values = (tid, r['player'], r['pos'], r['status'], r['injury'], r['reported'], r['note'], now)
            con.execute('INSERT OR REPLACE INTO injuries (team_id, player, pos, status, injury, reported, note, captured_at) VALUES (?,?,?,?,?,?,?,?)', values)
            con.execute("""INSERT INTO injury_history (team_id, player, pos, status, injury, reported, note, captured_at)
                           SELECT ?,?,?,?,?,?,?,? WHERE NOT EXISTS (
                               SELECT 1 FROM injury_history h WHERE h.team_id=? AND h.player=? AND h.status IS ? AND h.reported IS ?
                               AND h.captured_at = (SELECT MAX(captured_at) FROM injury_history WHERE team_id=? AND player=?))""",
                        (*values, tid, r['player'], r['status'], r['reported'], tid, r['player']))
            kept += 1
        con.commit()
    return {'teams': len(teams_seen), 'players': kept, 'unmatched_teams': unmatched}


if __name__ == '__main__':
    from db.db import init_db
    init_db()
    print(ingest())
