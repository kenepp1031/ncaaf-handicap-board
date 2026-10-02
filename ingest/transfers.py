"""Transfer portal ingest (247Sports), per FBS team.

Each school's portal page (247sports.com/college/<slug>/season/<season>-football/
transferportal/) embeds a JSON blob with every incoming and outgoing transfer
for that cycle: name, position, composite rating, stars, status, from/to. The
school slugs come from the Team Talent Composite page, which links every
school's roster. One pass is ~140 fetches, so this is cached for a week.

Context only. The talent composite already counts transfers who enrolled, and
there is no local sample to measure roster churn against; the dashboard shows
the in/out picture on each card and in the all-FBS table.
"""
from __future__ import annotations

import json
import re
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common import clean
from ingest.talent import SOURCE as TALENT_SOURCE, PAGE_QUERY as TALENT_PAGE_QUERY, AGENT as TALENT_AGENT, key
from db.db import connect

TEAM_PAGE = 'https://247sports.com/college/{slug}/season/{season}-football/transferportal/'
AGENT = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/128 Safari/537.36',
         'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8', 'Accept-Language': 'en-US,en;q=0.9'}
MAX_AGE_DAYS = 7
WORKERS = 4
MIN_TEAMS = 100


def _get(url, headers=AGENT):
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read().decode('utf-8', 'replace')


def slugs(season: int, get=_get) -> dict:
    """{talent key: 247 college slug} from the talent composite's roster links."""
    base = TALENT_SOURCE.format(season=season)
    out = {}
    for page in range(1, 7):
        html = get(base if page == 1 else base + TALENT_PAGE_QUERY.format(page=page), TALENT_AGENT)
        found = re.findall(r'class="rankings-page__name-link"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', html, re.S)
        new = 0
        for href, name in found:
            m = re.search(r'/college/([^/]+)/', href)
            k = key(clean(name))
            if m and k not in out:
                out[k] = m.group(1)
                new += 1
        if not new:
            break
    return out


def _initial_data(html: str) -> dict:
    i = html.find('window.__INITIAL_DATA__ = ')
    if i < 0:
        raise ValueError('no __INITIAL_DATA__ on page')
    j = html.find('</script>', i)
    blob = html[i + len('window.__INITIAL_DATA__ = '):j].strip().rstrip(';')
    return json.loads(re.sub(r':undefined\b', ':null', blob))


def parse_team(html: str) -> list[dict]:
    data = _initial_data(html)
    results = (data.get('main') or {}).get('teamTransferResults') or {}
    rows = []
    for direction, bucket in (('in', 'incoming'), ('out', 'outgoing')):
        for item in results.get(bucket) or []:
            p = item.get('player') or {}
            transfer = p.get('transfer') or {}
            source = (transfer.get('source') or {}).get('institution')
            dest = transfer.get('destination')
            if isinstance(dest, list):
                dest = dest[0].get('institution') if dest else None
            elif isinstance(dest, dict):
                dest = dest.get('institution')
            rows.append({'direction': direction, 'player_key': p.get('key'),
                         'player': ' '.join(x for x in (p.get('firstName'), p.get('lastName')) if x),
                         'pos': p.get('position'), 'rating': p.get('transferRating') or p.get('rating'),
                         'stars': p.get('starRating'), 'status': p.get('status') or None,
                         'from_school': source, 'to_school': dest,
                         'transfer_date': (p.get('transferDate') or '')[:10] or None})
    return [r for r in rows if r['player_key']]


def ingest(season: int, get=_get, force: bool = False) -> dict:
    now = datetime.now().astimezone()
    with connect() as con:
        if not force:
            row = con.execute('SELECT MAX(captured_at) AS d FROM transfers WHERE season=?', (season,)).fetchone()
            if row and row['d']:
                age = (now - datetime.fromisoformat(row['d'])).days
                if age < MAX_AGE_DAYS:
                    return {'skipped': f'cached copy is {age} day(s) old'}
        teams = [(r['team_id'], r['name']) for r in con.execute('SELECT team_id, name FROM teams WHERE fbs=1')]
    slug_map = slugs(season, get)
    plan = [(tid, name, slug_map.get(key(name))) for tid, name in teams]
    unmatched = [name for _, name, s in plan if not s]
    plan = [(tid, name, s) for tid, name, s in plan if s]
    if len(plan) < MIN_TEAMS:
        raise ValueError(f'only {len(plan)} FBS teams have a 247Sports slug; talent page layout changed?')

    def pull(item):
        tid, name, slug = item
        try:
            return tid, parse_team(get(TEAM_PAGE.format(slug=slug, season=season)))
        except Exception as exc:
            return tid, exc

    stamp = now.isoformat(timespec='seconds')
    fetched = failed = players = 0
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        results = list(pool.map(pull, plan))
    with connect() as con:
        for tid, rows in results:
            if isinstance(rows, Exception):
                failed += 1
                continue
            fetched += 1
            con.execute('DELETE FROM transfers WHERE season=? AND team_id=?', (season, tid))
            for r in rows:
                con.execute(
                    """INSERT OR REPLACE INTO transfers (season, team_id, direction, player_key, player, pos, rating, stars,
                            status, from_school, to_school, transfer_date, captured_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (season, tid, r['direction'], r['player_key'], r['player'], r['pos'], r['rating'], r['stars'],
                     r['status'], r['from_school'], r['to_school'], r['transfer_date'], stamp))
                players += 1
        con.commit()
    return {'teams': fetched, 'failed': failed, 'players': players, 'unmatched_teams': unmatched}


def summary(con, season: int) -> dict:
    """{team_id: {'in': n, 'out': n, 'in_avg': r, 'out_avg': r, 'in_top': [...], 'out_top': [...], 'net_rating': x}}.
    Rating sums above a 0.80 floor approximate "talent above a walk-on", so net_rating is
    roughly how much blue-chip weight the portal added (+) or drained (-)."""
    rows = con.execute('SELECT * FROM transfers WHERE season=?', (season,)).fetchall()
    out = {}
    for r in rows:
        t = out.setdefault(r['team_id'], {'in': [], 'out': []})
        t[r['direction']].append(dict(r))
    for tid, t in out.items():
        for d in ('in', 'out'):
            rated = [x['rating'] for x in t[d] if x['rating']]
            t[d + '_avg'] = round(sum(rated) / len(rated), 4) if rated else None
            t[d + '_top'] = sorted((x for x in t[d] if x['rating']), key=lambda x: -x['rating'])[:3]
            t[d + '_n'] = len(t[d])
        above = lambda xs: sum(max(0.0, (x['rating'] or 0) - 0.80) for x in xs)
        t['net_rating'] = round(above(t['in']) - above(t['out']), 2)
    return out


if __name__ == '__main__':
    import argparse
    from db.db import init_db
    p = argparse.ArgumentParser()
    p.add_argument('season', type=int)
    p.add_argument('--force', action='store_true')
    a = p.parse_args()
    init_db()
    print(ingest(a.season, force=a.force))
