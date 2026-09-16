"""DraftKings betting-splits ingest + closing-line archive.

Ported from feeds.py's parse_dk()/DK fetch loop and storage.py's Store
closing-line-capture logic (ESPN strips odds at kickoff, so the last capture
before kickoff becomes that game's closing line).
"""
from __future__ import annotations

import re
import sys
import time
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common import DK, clean, fetch_text, normal
from db.db import connect

DK_BUDGET_SECONDS = 40


def parse_dk(page: str) -> list[dict]:
    rows = []
    for block in re.split(r'<div class="tb-se border-', page)[1:]:
        title = re.search(r'<h5\b.*?</h5>', block, re.S)
        when = re.search(r'>(\d{1,2}/\d{1,2}),', block)
        if not title or not when:
            continue
        markets = re.split(r'<div class="tb-se-head\b[^>]*>', block)[1:]
        for market in markets:
            if not clean(market).startswith('Spread '):
                continue
            for side in re.split(r'<div class="tb-sodd\b[^>]*>', market)[1:]:
                label = re.search(r'<div class="tb-slipline[^>]*>(.*?)</div>', side, re.S)
                odds = re.search(r'class="tb-odd-s[^>]*>\s*([^<]+)', side)
                pct = re.findall(r'<div class="flex-1">\s*(\d+(?:\.\d+)?)%', side)
                if not label or not odds or len(pct) < 2:
                    continue
                match = re.fullmatch(r'(.*?)\s+([+−-]\d+(?:\.\d+)?)', clean(label[1]))
                if match:
                    rows.append({'team': normal(match[1]), 'month_day': when[1], 'spread': float(match[2].replace('−', '-')),
                                 'odds': float(clean(odds[1]).replace('−', '-')), 'handle': float(pct[0]), 'bets': float(pct[1])})
    return rows


def fetch_all_pages(budget_seconds: float = DK_BUDGET_SECONDS) -> tuple[list[dict], list[str]]:
    warnings = []
    first = fetch_text(DK)
    rows = parse_dk(first)
    pages = [int(x) for x in re.findall(r'tb_page=(\d+)', first)]
    deadline = time.monotonic() + budget_seconds
    last = min(max(pages, default=1), 20)
    for page in range(2, last + 1):
        if time.monotonic() > deadline:
            warnings.append(f'DraftKings splits stopped at page {page - 1} of {last} to keep the refresh quick.')
            break
        rows.extend(parse_dk(fetch_text(DK + f'&tb_page={page}')))
    if not rows:
        warnings.append('DraftKings supplied no readable spread splits.')
    return rows, warnings


def ingest() -> dict:
    now = datetime.now().astimezone().isoformat(timespec='seconds')
    rows, warnings = fetch_all_pages()
    with connect() as con:
        team_names = {r['team_id']: r['name'] for r in con.execute('SELECT team_id, name FROM teams')}
        by_key = {}
        for tid, name in team_names.items():
            by_key.setdefault(normal(name), tid)
        games = {r['game_id']: r for r in con.execute(
            "SELECT game_id, home_id, away_id, game_date, kickoff, completed FROM games WHERE completed=0")}
        # Index games by (team_key, month/day) to find a splits row's matching event.
        game_by_team_day = {}
        for g in games.values():
            d = date.fromisoformat(g['game_date'])
            for side, tid in (('home', g['home_id']), ('away', g['away_id'])):
                name = team_names.get(tid, '')
                game_by_team_day[(normal(name), f'{d.month}/{d.day}')] = g

        n_splits, n_lines = 0, 0
        today = date.today()
        for r in rows:
            g = game_by_team_day.get((r['team'], r['month_day']))
            con.execute(
                """INSERT INTO splits (game_id, team_key, month_day, spread, odds, handle_pct, bets_pct, captured_at)
                   VALUES (?,?,?,?,?,?,?,?)
                   ON CONFLICT(team_key, month_day) DO UPDATE SET
                       game_id=excluded.game_id, spread=excluded.spread, odds=excluded.odds,
                       handle_pct=excluded.handle_pct, bets_pct=excluded.bets_pct, captured_at=excluded.captured_at""",
                (g['game_id'] if g else None, r['team'], r['month_day'], r['spread'], r['odds'], r['handle'], r['bets'], now))
            n_splits += 1
            if not g:
                continue
            d = date.fromisoformat(g['game_date'])
            if d < today:
                continue
            home_is_this_team = normal(team_names.get(g['home_id'], '')) == r['team']
            home_spread = r['spread'] if home_is_this_team else -r['spread']
            home_odds = r['odds'] if home_is_this_team else None
            away_odds = r['odds'] if not home_is_this_team else None
            _capture_line(con, g['game_id'], now, g['kickoff'], home_spread, None, home_odds, away_odds, 'DraftKings Network')
            con.execute(
                """UPDATE games SET home_spread=?, market_source='DraftKings Network', market_observed_at=?
                   WHERE game_id=? AND completed=0""",
                (home_spread, now, g['game_id']))
            n_lines += 1
        con.commit()
    return {'splits': n_splits, 'lines_captured': n_lines, 'warnings': warnings}


def _capture_line(con, game_id, captured_at, kickoff, home_spread, total, home_odds, away_odds, source):
    """One row per observed change — skip if identical to the latest known capture."""
    latest = con.execute(
        """SELECT home_spread, total, home_odds, away_odds FROM line_history
           WHERE game_id=? ORDER BY captured_at DESC LIMIT 1""", (game_id,)).fetchone()
    if latest and (latest['home_spread'], latest['total'], latest['home_odds'], latest['away_odds']) == (home_spread, total, home_odds, away_odds):
        return False
    con.execute(
        """INSERT OR IGNORE INTO line_history (game_id, captured_at, kickoff, home_spread, total, home_odds, away_odds, source)
           VALUES (?,?,?,?,?,?,?,?)""",
        (game_id, captured_at, kickoff, home_spread, total, home_odds, away_odds, source))
    return True


if __name__ == '__main__':
    print(ingest())
