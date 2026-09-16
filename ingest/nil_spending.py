"""School spending ingest (nil-ncaa.com): roster cost + athletic-dept expenses.

Ported from nil.py's scrape/parse half. The fit/margin_shift half (which is a
pure function of ratings, not an ingest concern) lives in ratings/nil_prior.py.
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

SOURCE = 'https://nil-ncaa.com/'
AGENT = {'User-Agent': 'Mozilla/5.0 (compatible; cfb-handicap/1.0)'}

CONFERENCE_KEYS = {('miami', 'MAC'): 'miamiohio'}
ALIASES = {'louisianastate': 'lsu', 'southerncal': 'usc', 'southerncalifornia': 'usc',
           'brighamyoung': 'byu', 'texaschristian': 'tcu', 'southernmethodist': 'smu',
           'centralflorida': 'ucf', 'southernmississippi': 'southernmiss',
           'louisianamonroe': 'ulmonroe', 'louisianalafayette': 'louisiana',
           'floridainternational': 'fiu', 'floridaatlantic': 'fau',
           'texasarlington': 'uta', 'alabamabirmingham': 'uab', 'texassanantonio': 'utsa',
           'texaselpaso': 'utep', 'nevadalasvegas': 'unlv', 'miamiflorida': 'miami',
           'mississippi': 'olemiss', 'nicholls': 'nichollsstate'}


def key(name: str) -> str:
    plain = normal(re.sub(r'\s*[-–]\s*', ' ', name or ''))
    return ALIASES.get(plain, plain)


def _money(cell):
    digits = re.sub(r'[^0-9]', '', cell or '')
    return int(digits) if digits else None


def _tables(page):
    for table in re.findall(r'<table.*?</table>', page, re.S):
        rows = []
        for row in re.findall(r'<tr.*?</tr>', table, re.S):
            cells = [clean(c) for c in re.findall(r'<t[dh][^>]*>(.*?)</t[dh]>', row, re.S)]
            if any(cells):
                rows.append(cells)
        if rows:
            yield rows


def parse(page: str) -> dict:
    roster, expenses, names = {}, {}, {}
    for rows in _tables(page):
        header = rows[0]
        title = header[0] if header else ''
        if 'Roster Cost' in title and len(header) >= 3 and header[1] == 'Conference':
            for row in rows[1:]:
                amount = _money(row[2]) if len(row) >= 3 else None
                if row[0] and amount:
                    roster[key(row[0])] = amount
                    names.setdefault(key(row[0]), row[0])
        elif 'Annual Expenses' in title and len(header) >= 6:
            for row in rows[1:]:
                if len(row) < 6 or row[2] not in ('FBS', 'FCS'):
                    continue
                amount = _money(row[5])
                if not row[0] or not amount:
                    continue
                k = CONFERENCE_KEYS.get((key(row[0]), row[3]), key(row[0]))
                expenses.setdefault(k, amount)
                names.setdefault(k, row[0] if k == key(row[0]) else f'{row[0]} ({row[3]})')
    if not roster and not expenses:
        raise ValueError('No spending tables found on the source page')
    return {'roster': roster, 'expenses': expenses, 'names': names}


def ingest(season: int) -> dict:
    now = datetime.now().astimezone().isoformat(timespec='seconds')
    request = urllib.request.Request(SOURCE, headers=AGENT)
    with urllib.request.urlopen(request, timeout=45) as response:
        page = response.read().decode('utf-8', 'replace')
    data = parse(page)
    keys = set(data['roster']) | set(data['expenses'])
    with connect() as con:
        for k in keys:
            con.execute(
                """INSERT INTO nil_spend (school_key, season, school_name, roster_cost, athletic_expenses, captured_at)
                   VALUES (?,?,?,?,?,?)
                   ON CONFLICT(school_key, season) DO UPDATE SET
                       school_name=excluded.school_name, roster_cost=excluded.roster_cost,
                       athletic_expenses=excluded.athletic_expenses, captured_at=excluded.captured_at""",
                (k, season, data['names'].get(k, k), data['roster'].get(k), data['expenses'].get(k), now))
        con.commit()
    return {'roster_schools': len(data['roster']), 'expense_schools': len(data['expenses'])}


if __name__ == '__main__':
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument('season', type=int)
    a = p.parse_args()
    print(ingest(a.season))
