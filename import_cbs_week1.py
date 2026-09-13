"""Import CBS Sports' published 2026 Week 1 FBS lines into the local archive.

The app started archiving ESPN lines on September 10, after Week 1.  This
one-time importer restores the historical CBS board without misattributing it
to ESPN.  Each line is attached only after its two teams and final score match
the already-cached ESPN result.
"""
import argparse
import difflib
import json
import sqlite3
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

from lxml import html

from feeds import normal


URL = 'https://www.cbssports.com/college-football/odds/FBS/2026/regular/week-1/'
DATA = Path(__file__).parent / 'data'
SOURCE = 'CBS Sports historical Week 1 board'


def _text(node, xpath):
    return ' '.join(' '.join(node.xpath(xpath)).split())


def cbs_games(page):
    """Return away/home score and line records from the archived CBS board."""
    document = html.fromstring(page)
    records = []
    for table in document.xpath('//table[@data-game-abbrev]'):
        rows = table.xpath('.//tbody/tr')[:2]
        if len(rows) != 2:
            continue
        teams = [_text(row, ".//span[contains(@class, 'OddsBlock-teamText--long')]/a/text()") for row in rows]
        scores = [_text(row, ".//td[contains(@class, 'OddsBlock-betOdds--score')]/text()") for row in rows]
        text_class = "contains(concat(' ', normalize-space(@class), ' '), ' BetButton-text ')"
        spreads = [_text(row, ".//td[contains(@class, 'OddsBlock-betOdds--spread')]//div["+text_class+"]/text()") for row in rows]
        totals = [_text(row, ".//td[contains(@class, 'OddsBlock-betOdds--total')]//div["+text_class+"]/text()") for row in rows]
        if not all(teams) or not all(score.isdigit() for score in scores) or not all(spreads):
            continue
        # CBS lists visitor first, then home team.  The app stores home lines.
        records.append({'away': teams[0], 'home': teams[1], 'away_score': int(scores[0]),
                        'home_score': int(scores[1]), 'home_spread': float(spreads[1]),
                        'total': float(totals[1][1:]) if totals[1][1:].replace('.', '', 1).isdigit() else None})
    return records


def match(record, events):
    """Find the uniquely corroborated ESPN event for a CBS record."""
    away, home = normal(record['away']), normal(record['home'])
    scored = []
    for event in events:
        score = (difflib.SequenceMatcher(None, away, normal(event['away'])).ratio() +
                 difflib.SequenceMatcher(None, home, normal(event['home'])).ratio())
        scored.append((score, event))
    score, event = max(scored, key=lambda item: item[0])
    if score < 1.1 or event['away_score'] != record['away_score'] or event['home_score'] != record['home_score']:
        raise ValueError(f"Could not verify CBS game {record['away']} at {record['home']}")
    return event


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    page = urllib.request.urlopen(URL, timeout=30).read()
    records = cbs_games(page)
    payload = json.loads((DATA / 'live.json').read_text(encoding='utf-8'))
    events = [event for event in payload['events'] if event.get('completed') and event.get('week') == 1]
    if len(records) != len(events):
        raise ValueError(f'CBS returned {len(records)} records; expected {len(events)} completed Week 1 events')
    rows = []
    for record in records:
        event = match(record, events)
        kickoff = datetime.fromisoformat(event['kickoff'])
        # This is an imported historical record, not a timestamp observed by
        # this app.  It is placed immediately before kickoff so the existing
        # archive can restore it without treating it as a live/postgame line.
        captured_at = (kickoff - timedelta(seconds=1)).isoformat()
        rows.append((event['id'], captured_at, event['kickoff'], record['home_spread'], record['total'],
                     None, None, SOURCE))
    print(f'CBS records matched: {len(rows)}')
    if args.dry_run:
        return
    with sqlite3.connect(DATA / 'picks.sqlite3') as db:
        db.executemany('INSERT OR IGNORE INTO market_lines VALUES (?,?,?,?,?,?,?,?)', rows)
    print('Historical Week 1 lines imported.')


if __name__ == '__main__':
    main()
