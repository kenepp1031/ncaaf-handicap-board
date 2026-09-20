"""CBS Sports odds-page ingest: closing spreads/totals for finished games.

ESPN strips a game's odds object at kickoff, so completed games have no market
line to grade against. CBS keeps the closing spread and total on its weekly odds
pages, which this fills in wherever a game still has none.
"""
from __future__ import annotations

import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common import fbs_key, fetch_text, normal
from db.db import connect

CBS_ODDS = 'https://www.cbssports.com/college-football/odds/FBS/{season}/regular/week-{week}/'
SOURCE = 'CBS Sports'


def _number(text):
    text = (text or '').strip().replace('−', '-')
    if text.upper() in ('PK', 'EVEN', 'EV'):
        return 0.0
    m = re.fullmatch(r'[ou]?([+-]?\d+(?:\.\d+)?)', text)
    return float(m[1]) if m else None


def _cell(row, kind):
    m = re.search(rf'OddsBlock-betOdds--{kind}\b.*?BetButton-text"\s*>\s*([^<]*?)\s*<', row, re.S)
    return _number(m[1]) if m else None


def parse_page(page: str) -> list[dict]:
    games = []
    for abbrev, body in re.findall(r'<table\s+class="OddsBlock-game[^"]*"\s+data-game-abbrev=(\S+)\s+data-game-id=\d+\s*>(.*?)</table>', page, re.S):
        m = re.fullmatch(r'NCAAF_(\d{4})(\d{2})(\d{2})_[^@]+@.+', abbrev)
        if not m:
            continue
        rows = [r for r in re.split(r'<tr\b[^>]*>', body)[1:] if 'OddsBlock-team' in r]
        if len(rows) != 2:
            continue
        sides = []
        for r in rows:
            slug = re.search(r'/college-football/teams/[^/]+/([^/]+)/', r)
            score = re.search(r'OddsBlock-betOdds--score[^>]*>\s*([^<]*?)\s*<', r)
            sides.append({'slug': slug[1] if slug else '', 'score': _number(score[1]) if score else None,
                          'spread': _cell(r, 'spread'), 'total': _cell(r, 'total')})
        away, home = sides
        # Each row carries that side's own best line, so the midpoint is the consensus close.
        games.append({'date': date(int(m[1]), int(m[2]), int(m[3])), 'away': away, 'home': home,
                      'home_spread': _mid(home['spread'], None if away['spread'] is None else -away['spread']),
                      'total': _mid(home['total'], away['total'])})
    return games


def _mid(a, b):
    vals = [v for v in (a, b) if v is not None]
    return round(sum(vals) / len(vals) * 4) / 4 if vals else None


# CBS slugs whose school segment shares no prefix with the ESPN name. Kept here
# rather than in common._ALIASES because most are FCS schools and fbs_key() drives
# FCS pooling -- widening that table would change which teams pool.
SLUG_ALIASES = {
    'louisianamonroe': 'ulmonroe',
    'semissourist': 'southeastmissouristate',
    'sdakotast': 'southdakotastate',
    'ncat': 'northcarolinaat',
    'citadel': 'thecitadel',
    'liu': 'longislanduniversity',
    'utrgv': 'utriograndevalley',
    'etsu': 'easttennesseestate',
    'southeasternlouisiana': 'selouisiana',
}


def _slug_school(slug, known):
    """Resolve a CBS slug to one school key, or None.

    CBS slugs run school-then-mascot ('middle-tenn-blue-raiders') with no marker
    for the split, so each hyphen prefix is a candidate school name. Longest
    first, take the first one that names a team we actually have. Stopping at the
    first real hit is what keeps 'miami-oh-redhawks' off Miami: 'miamioh' matches
    before the walk ever reaches the bare 'miami'.

    Running the prefixes through the alias tables the rest of the app already uses
    also resolves spellings that share no prefix with ESPN's -- 'fiu' to Florida
    International, 'connecticut' to UConn -- which a raw startswith() dropped
    silently, costing 24 games of lines across weeks 1-4 of 2026.
    """
    parts = [p for p in slug.lower().split('-') if p]
    for n in range(len(parts), 0, -1):
        key = normal(''.join(parts[:n]))
        cand = SLUG_ALIASES.get(key, fbs_key(key))
        if cand in known:
            return cand
    return None


def _match_len(espn_name, slug, known=frozenset()):
    key = re.sub('[^a-z0-9]', '', slug.lower())
    raw = re.sub('[^a-z0-9]', '', (espn_name or '').lower())
    school = _slug_school(slug, known)
    if school is not None:
        # Decisive: the slug names exactly one school, so anyone else scores 0.
        return 100 if school == fbs_key(espn_name) else 0
    best = 0
    for cand in {raw, normal(espn_name)}:
        if cand and key.startswith(cand):
            best = max(best, len(cand))
    return best


def _find_game(cbs, games_by_date, team_names, known=frozenset()):
    for delta in (0, 1, -1):
        candidates = games_by_date.get(cbs['date'] + timedelta(days=delta), [])
        scored = []
        for g in candidates:
            h = _match_len(team_names.get(g['home_id']), cbs['home']['slug'], known)
            a = _match_len(team_names.get(g['away_id']), cbs['away']['slug'], known)
            if h and a:
                scored.append((h + a, g))
        if scored:
            return max(scored, key=lambda s: s[0])[1]
    return None


def ingest_week(con, season: int, week: int, team_names, games_by_date, known=None) -> dict:
    page = fetch_text(CBS_ODDS.format(season=season, week=week))
    known = known if known is not None else {fbs_key(n) for n in team_names.values()}
    filled, mismatched, unmatched = 0, 0, 0
    now = datetime.now().astimezone().isoformat(timespec='seconds')
    for cbs in parse_page(page):
        g = _find_game(cbs, games_by_date, team_names, known)
        if g is None:
            unmatched += 1
            continue
        if g['completed'] and g['home_score'] is not None and cbs['home']['score'] is not None:
            if (g['home_score'], g['away_score']) != (cbs['home']['score'], cbs['away']['score']):
                mismatched += 1
                continue
        if cbs['home_spread'] is None and cbs['total'] is None:
            continue
        con.execute(
            """UPDATE games SET
                   home_spread=COALESCE(home_spread, ?), away_spread=COALESCE(away_spread, ?),
                   total=COALESCE(total, ?),
                   market_source=CASE WHEN home_spread IS NULL AND ? IS NOT NULL THEN ? ELSE market_source END,
                   odds_status=CASE WHEN home_spread IS NULL AND ? IS NOT NULL THEN 'Available' ELSE odds_status END,
                   market_observed_at=CASE WHEN home_spread IS NULL AND ? IS NOT NULL THEN ? ELSE market_observed_at END
               WHERE game_id=?""",
            (cbs['home_spread'], None if cbs['home_spread'] is None else -cbs['home_spread'], cbs['total'],
             cbs['home_spread'], SOURCE + (' closing' if g['completed'] else ''),
             cbs['home_spread'], cbs['home_spread'], now, g['game_id']))
        if g['completed'] and cbs['home_spread'] is not None and not con.execute(
                'SELECT 1 FROM line_history WHERE game_id=?', (g['game_id'],)).fetchone():
            con.execute(
                """INSERT OR IGNORE INTO line_history (game_id, captured_at, kickoff, home_spread, total, home_odds, away_odds, source)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (g['game_id'], g['kickoff'], g['kickoff'], cbs['home_spread'], cbs['total'], None, None, SOURCE))
        filled += 1
    return {'week': week, 'filled': filled, 'score_mismatch': mismatched, 'unmatched': unmatched}


def ingest(season: int, weeks: list[int] | None = None) -> dict:
    with connect() as con:
        team_names = {r['team_id']: r['name'] for r in con.execute('SELECT team_id, name FROM teams')}
        if weeks is None:
            weeks = [r[0] for r in con.execute(
                """SELECT DISTINCT week FROM games WHERE season=? AND week_type=2 AND week IS NOT NULL
                   AND (home_spread IS NULL OR total IS NULL) AND game_date <= date('now', '+7 days') ORDER BY week""", (season,))]
        known = {fbs_key(n) for n in team_names.values()}
        games_by_date = {}
        for g in con.execute('SELECT * FROM games WHERE season=? AND week_type=2', (season,)):
            games_by_date.setdefault(date.fromisoformat(g['game_date']), []).append(dict(g))
        results = []
        for week in weeks:
            try:
                results.append(ingest_week(con, season, week, team_names, games_by_date, known))
            except Exception as e:
                results.append({'week': week, 'error': str(e)})
            con.commit()
    return {'season': season, 'weeks': results}


if __name__ == '__main__':
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument('season', type=int)
    p.add_argument('--weeks', type=str, help='Comma-separated week numbers (default: weeks still missing lines)')
    a = p.parse_args()
    print(ingest(a.season, [int(w) for w in a.weeks.split(',')] if a.weeks else None))
