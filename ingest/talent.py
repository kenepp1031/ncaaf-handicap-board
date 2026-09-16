"""Roster-talent ingest (247Sports Team Talent Composite).

Ported from talent.py's scrape/parse half. The fit/margin_shift half lives in
ratings/talent_prior.py.
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

SOURCE = 'https://247sports.com/season/{season}-football/collegeteamtalentcomposite/'
PAGE_QUERY = '?ViewPath=~%2FViews%2FSkyNet%2FInstitutionRanking%2F_SimpleSetForSeason.ascx&Page={page}'
AGENT = {'User-Agent': 'Mozilla/5.0 (compatible; cfb-handicap/1.0)'}
MAX_PAGES = 6
MIN_SCHOOLS = 100

ALIASES = {'sanjosstate': 'sanjosestate', 'louisianamonroe': 'ulmonroe', 'fiu': 'floridainternational'}


def key(name: str) -> str:
    return ALIASES.get(normal(name or ''), normal(name or ''))


def _number(fragment):
    found = re.search(r'-?\d+(?:\.\d+)?', clean(fragment or '').replace(',', ''))
    return float(found[0]) if found else None


def parse(page: str) -> list[dict]:
    rows = []
    for chunk in page.split('<li class="rankings-page__list-item">')[1:]:
        chunk = chunk.split('data-react-container', 1)[0]
        fields = {name: re.search(r'class="%s">(.*?)</div>' % name, chunk, re.S)
                  for name in ('primary', 'total', 'avg', 'points')}
        link = re.search(r'class="rankings-page__name-link"[^>]*>(.*?)</a>', chunk, re.S)
        team = clean(link[1]) if link else ''
        average = _number(fields['avg'][1]) if fields['avg'] else None
        if not team or average is None:
            continue
        value = lambda name: _number(fields[name][1]) if fields[name] else None
        stars = {int(s): int(n) for s, n in re.findall(r'<h2>(\d)-Star</h2>\s*<div[^>]*>\s*(\d+)', chunk)}
        rank, players = value('primary'), value('total')
        rows.append({'team': team, 'rank': None if rank is None else int(rank), 'points': value('points'),
                     'avg_rating': average, 'players': None if players is None else int(players),
                     'five_star': stars.get(5, 0), 'four_star': stars.get(4, 0), 'three_star': stars.get(3, 0)})
    return rows


def _get(url):
    request = urllib.request.Request(url, headers=AGENT)
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read().decode('utf-8', 'replace')


def fetch_season(season: int, get=_get) -> dict:
    base = SOURCE.format(season=season)
    schools = {}
    for page in range(1, MAX_PAGES + 1):
        new = [r for r in parse(get(base if page == 1 else base + PAGE_QUERY.format(page=page)))
               if key(r['team']) not in schools]
        if not new:
            break
        for row in new:
            schools[key(row['team'])] = row
    if len(schools) < MIN_SCHOOLS:
        raise ValueError(f'247Sports talent composite returned {len(schools)} schools: layout changed or not yet published')
    return schools


MAX_AGE_DAYS = 7


def ingest(season: int, get=_get, force: bool = False) -> dict:
    now = datetime.now().astimezone().isoformat(timespec='seconds')
    if not force:
        with connect() as con:
            row = con.execute('SELECT MAX(captured_at) AS d FROM talent WHERE season=?', (season,)).fetchone()
        if row and row['d']:
            age_days = (datetime.now().astimezone() - datetime.fromisoformat(row['d'])).days
            if age_days < MAX_AGE_DAYS:
                return {'skipped': f'cached copy is {age_days} day(s) old'}
    schools = fetch_season(season, get)
    with connect() as con:
        for k, row in schools.items():
            con.execute(
                """INSERT INTO talent (school_key, season, school_name, rank, points, avg_rating, players,
                        five_star, four_star, three_star, captured_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(school_key, season) DO UPDATE SET
                       school_name=excluded.school_name, rank=excluded.rank, points=excluded.points,
                       avg_rating=excluded.avg_rating, players=excluded.players, five_star=excluded.five_star,
                       four_star=excluded.four_star, three_star=excluded.three_star, captured_at=excluded.captured_at""",
                (k, season, row['team'], row['rank'], row['points'], row['avg_rating'], row['players'],
                 row['five_star'], row['four_star'], row['three_star'], now))
        con.commit()
    return {'schools': len(schools)}


if __name__ == '__main__':
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument('season', type=int)
    a = p.parse_args()
    print(ingest(a.season))
