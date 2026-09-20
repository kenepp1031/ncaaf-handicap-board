"""Kalshi prediction-market money on each game's winner market.

Kalshi is an exchange, so unlike the DraftKings splits it publishes real dollars:
every trade with its size, price and which side the taker bought. A taker buying
"Yes" on a team is betting that team; buying "No" is betting the other one.
No login is needed for market data.
"""
from __future__ import annotations

import re
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common import fetch_json, normal
from db.db import connect

API = 'https://api.elections.kalshi.com/trade-api/v2'
SERIES = 'KXNCAAFGAME'
BUDGET_SECONDS = 60
MAX_TRADE_PAGES = 5     # 1000 trades a page, newest first


_KALSHI_NAMES = {
    'louisianamonroe': 'ulmonroe', 'southeasternlouisiana': 'selouisiana',
    'tennesseemartin': 'utmartin', 'nichollsstate': 'nicholls',
}


def team_key(name: str) -> str:
    """Kalshi writes 'Iowa St.' where every other source says 'Iowa State'."""
    key = normal(re.sub(r'\bSt\.?$', 'State', (name or '').strip()))
    return _KALSHI_NAMES.get(key, key)


def fetch_events() -> list[dict]:
    events, cursor = [], ''
    for _ in range(10):
        page = fetch_json(f'{API}/events?series_ticker={SERIES}&status=open&limit=200&with_nested_markets=true'
                          + (f'&cursor={quote(cursor)}' if cursor else ''))
        events.extend(page.get('events', []))
        cursor = page.get('cursor') or ''
        if not cursor:
            break
    return events


def fetch_trades(ticker: str) -> list[dict]:
    trades, cursor = [], ''
    for _ in range(MAX_TRADE_PAGES):
        page = fetch_json(f'{API}/markets/trades?ticker={quote(ticker)}&limit=1000'
                          + (f'&cursor={quote(cursor)}' if cursor else ''))
        trades.extend(page.get('trades', []))
        cursor = page.get('cursor') or ''
        if not cursor:
            break
    return trades


def tally(trades_by_team: dict[str, list[dict]], since: str | None = None) -> dict:
    """Dollars takers put on each team, and the biggest single trade.

    trades_by_team maps each team's key to the trades in its own "team wins" market.
    Trades before `since` (ISO time) are skipped.
    """
    teams = list(trades_by_team)
    money = {t: 0.0 for t in teams}
    biggest = {'dollars': 0.0, 'team': None, 'at': None}
    for team, trades in trades_by_team.items():
        other = next((t for t in teams if t != team), None)
        for tr in trades:
            if since and tr.get('created_time', '') < since:
                continue
            side = tr.get('taker_side')
            backed = team if side == 'yes' else other
            if backed is None:
                continue
            price = float(tr.get('yes_price_dollars' if side == 'yes' else 'no_price_dollars') or 0)
            dollars = float(tr.get('count_fp') or 0) * price
            money[backed] += dollars
            if dollars > biggest['dollars']:
                biggest = {'dollars': dollars, 'team': backed, 'at': tr.get('created_time')}
    return {'money': money, 'biggest': biggest}


def ingest(budget_seconds: float = BUDGET_SECONDS) -> dict:
    now = datetime.now().astimezone().isoformat(timespec='seconds')
    day_ago = (datetime.utcnow() - timedelta(hours=24)).isoformat(timespec='seconds') + 'Z'
    warnings = []
    events = fetch_events()
    deadline = time.monotonic() + budget_seconds
    n = 0
    with connect() as con:
        team_names = {r['team_id']: r['name'] for r in con.execute('SELECT team_id, name FROM teams')}
        game_by_pair = {}
        for g in con.execute('SELECT game_id, home_id, away_id, game_date FROM games WHERE completed=0 AND game_date>=?',
                             (date.today().isoformat(),)):
            pair = frozenset((normal(team_names.get(g['home_id'], '')), normal(team_names.get(g['away_id'], ''))))
            # Earliest upcoming meeting wins if the same two teams are listed twice.
            if pair not in game_by_pair or g['game_date'] < game_by_pair[pair]['game_date']:
                game_by_pair[pair] = g
        for ev in events:
            markets = {team_key(m.get('yes_sub_title', '')): m for m in ev.get('markets', [])}
            g = game_by_pair.get(frozenset(markets))
            if not g or len(markets) != 2:
                continue
            if time.monotonic() > deadline:
                warnings.append(f'Kalshi stopped after {n} games to keep the refresh quick.')
                break
            home_key = normal(team_names.get(g['home_id'], ''))
            away_key = next(k for k in markets if k != home_key)
            trades = {k: fetch_trades(m['ticker']) for k, m in markets.items()}
            total, last_day = tally(trades), tally(trades, since=day_ago)
            big = total['biggest']
            con.execute(
                """INSERT INTO kalshi (game_id, event_ticker, home_price, away_price, home_dollars, away_dollars,
                                       home_dollars_24h, away_dollars_24h, biggest_dollars, biggest_side, biggest_at, captured_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(game_id) DO UPDATE SET
                       event_ticker=excluded.event_ticker, home_price=excluded.home_price, away_price=excluded.away_price,
                       home_dollars=excluded.home_dollars, away_dollars=excluded.away_dollars,
                       home_dollars_24h=excluded.home_dollars_24h, away_dollars_24h=excluded.away_dollars_24h,
                       biggest_dollars=excluded.biggest_dollars, biggest_side=excluded.biggest_side,
                       biggest_at=excluded.biggest_at, captured_at=excluded.captured_at""",
                (g['game_id'], ev.get('event_ticker'),
                 float(markets[home_key].get('last_price_dollars') or 0), float(markets[away_key].get('last_price_dollars') or 0),
                 total['money'][home_key], total['money'][away_key],
                 last_day['money'][home_key], last_day['money'][away_key],
                 big['dollars'], None if big['team'] is None else ('home' if big['team'] == home_key else 'away'),
                 big['at'], now))
            n += 1
        con.commit()
    if not n:
        warnings.append('Kalshi listed no markets matching upcoming games.')
    return {'games': n, 'events': len(events), 'warnings': warnings}


if __name__ == '__main__':
    print(ingest())
