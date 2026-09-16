"""ESPN scoreboard ingest: games, teams, and the week calendar.

Ported from feeds.py's parse_events()/refresh() scoreboard half. Writes
straight to SQLite instead of building an in-memory events dict.
"""
from __future__ import annotations

import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common import ESPN, fetch_json
from db.db import connect


def number(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_events(data: dict) -> list[dict]:
    events = []
    for event in data.get('events', []):
        comp = event['competitions'][0]
        sides = {c['homeAway']: c for c in comp['competitors']}
        if 'home' not in sides or 'away' not in sides:
            continue
        dt = datetime.fromisoformat(event['date'].replace('Z', '+00:00')).astimezone()
        status = comp.get('status', event.get('status', {})).get('type', {})
        row = {'id': event['id'], 'game_date': dt.date().isoformat(), 'kickoff': dt.isoformat(),
               'season': event.get('season', {}).get('year'), 'week': event.get('week', {}).get('number'),
               'status': status.get('description', 'Unknown'), 'completed': bool(status.get('completed')),
               'neutral': comp.get('neutralSite', False), 'market_source': '',
               'market_observed_at': datetime.now().astimezone().isoformat(timespec='seconds')}
        row['season_type'] = event.get('season', {}).get('type', 2)
        row['venue'] = comp.get('venue', {})
        odds_list = comp.get('odds', [])
        odds = next((o for o in odds_list if o.get('provider', {}).get('name') == 'DraftKings'), odds_list[0] if odds_list else {})
        row['market_source'] = (odds.get('provider', {}).get('name', '') + ' via ESPN').strip() if odds else ''
        for side, c in sides.items():
            team = c['team']
            row[side] = team.get('location', team['displayName'])
            row[side + '_id'] = str(team['id'])
            row[side + '_logo'] = team.get('logo', '')
            row[side + '_color'] = team.get('color')
            row[side + '_alt_color'] = team.get('alternateColor')
            row[side + '_record'] = next((r.get('summary', '') for r in c.get('records', []) if r.get('type') == 'total'), '')
            row[side + '_rank'] = c.get('curatedRank', {}).get('current', 99)
            row[side + '_score'] = int(c.get('score', 0)) if row['completed'] else None
            closing = odds.get('pointSpread', {}).get(side, {}).get('close', {})
            row[side + '_spread'] = number(closing.get('line'))
            row[side + '_odds'] = number(closing.get('odds'))
        if row['home_spread'] is None:
            raw = number(odds.get('spread'))
            home_favorite = odds.get('homeTeamOdds', {}).get('favorite')
            away_favorite = odds.get('awayTeamOdds', {}).get('favorite')
            if raw is not None and (home_favorite is True or away_favorite is True or raw == 0):
                row['home_spread'] = -abs(raw) if home_favorite else abs(raw)
                row['away_spread'] = -row['home_spread']
        row['odds_status'] = 'Available' if row['home_spread'] is not None else ('Provider supplied no spread' if odds else 'No odds supplied by ESPN')
        row['total'] = number(odds.get('overUnder'))
        events.append(row)
    return events


def upsert_events(con, events: list[dict]) -> int:
    import json as _json
    teams_seen = {}
    for r in events:
        for side in ('home', 'away'):
            teams_seen[r[side + '_id']] = (r[side], r[side + '_logo'], r[side + '_color'], r[side + '_alt_color'])
    for tid, (name, logo, color, alt) in teams_seen.items():
        con.execute(
            """INSERT INTO teams (team_id, name, logo, color, alt_color) VALUES (?,?,?,?,?)
               ON CONFLICT(team_id) DO UPDATE SET name=excluded.name, logo=excluded.logo,
                   color=COALESCE(excluded.color, teams.color), alt_color=COALESCE(excluded.alt_color, teams.alt_color)""",
            (tid, name, logo, color, alt))
    for r in events:
        con.execute(
            """INSERT INTO games (game_id, season, week, week_type, game_date, kickoff, status, completed,
                    neutral, home_id, away_id, home_score, away_score, home_spread, away_spread,
                    home_odds, away_odds, total, odds_status, market_source, market_observed_at, venue_json)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(game_id) DO UPDATE SET
                    season=excluded.season, week=excluded.week, week_type=excluded.week_type,
                    game_date=excluded.game_date, kickoff=excluded.kickoff, status=excluded.status,
                    completed=excluded.completed, neutral=excluded.neutral,
                    home_id=excluded.home_id, away_id=excluded.away_id,
                    home_score=excluded.home_score, away_score=excluded.away_score,
                    -- Once a game kicks off ESPN strips its odds object entirely;
                    -- don't let a later scoreboard poll null out a spread we
                    -- already had (ingest.dk_lines/line_history is the closing-
                    -- line source of truth after kickoff anyway).
                    home_spread=CASE WHEN excluded.home_spread IS NOT NULL THEN excluded.home_spread ELSE games.home_spread END,
                    away_spread=CASE WHEN excluded.away_spread IS NOT NULL THEN excluded.away_spread ELSE games.away_spread END,
                    home_odds=CASE WHEN excluded.home_odds IS NOT NULL THEN excluded.home_odds ELSE games.home_odds END,
                    away_odds=CASE WHEN excluded.away_odds IS NOT NULL THEN excluded.away_odds ELSE games.away_odds END,
                    total=CASE WHEN excluded.total IS NOT NULL THEN excluded.total ELSE games.total END,
                    odds_status=excluded.odds_status, market_source=excluded.market_source,
                    market_observed_at=excluded.market_observed_at, venue_json=excluded.venue_json""",
            (r['id'], r['season'], r['week'], r['season_type'], r['game_date'], r['kickoff'], r['status'],
             1 if r['completed'] else 0, 1 if r['neutral'] else 0, r['home_id'], r['away_id'],
             r['home_score'], r['away_score'], r['home_spread'], r['away_spread'], r['home_odds'], r['away_odds'],
             r['total'], r['odds_status'], r['market_source'], r['market_observed_at'], _json.dumps(r['venue'])))
    con.commit()
    return len(events)


def upsert_weeks(con, season: int, calendar: list) -> int:
    n = 0
    for period in calendar:
        if not isinstance(period, dict):
            continue
        if int(period.get('value', 0)) not in (2, 3):
            continue
        for entry in period.get('entries', []):
            label = entry['label'] if int(period['value']) == 2 else period['label'] + ' ' + entry['label']
            con.execute(
                """INSERT INTO weeks (season, week_type, number, label, start_date, end_date, detail)
                   VALUES (?,?,?,?,?,?,?)
                   ON CONFLICT(season, week_type, number) DO UPDATE SET
                       label=excluded.label, start_date=excluded.start_date, end_date=excluded.end_date, detail=excluded.detail""",
                (season, int(period['value']), int(entry['value']), label, entry['startDate'], entry['endDate'], entry.get('detail', '')))
            n += 1
    con.commit()
    return n


def _fetch_day(day: date) -> dict:
    # limit=1000 makes ESPN silently fall back to its 25-game default; 300 returns the full slate.
    return fetch_json(ESPN + f"scoreboard?limit=300&groups=80&dates={day.strftime('%Y%m%d')}")


def ingest(season: int, week_start: date | None = None, week_end: date | None = None, full_season: bool = False) -> dict:
    """Pull the scoreboard for a date window (or the whole season) and persist it.

    ESPN's dates=START-END range query currently rejects every request with a
    400 ("Failed to get events endpoint"), regardless of range length -- a
    change on ESPN's side, not specific to this app. A single dates=YYYYMMDD
    still works, so this fetches one day at a time and aggregates.
    """
    if full_season or week_start is None:
        start_d, end_d = date(season, 8, 1), date(season + 1, 2, 1)
    else:
        start_d = week_start
        end_d = week_end or week_start + timedelta(days=6)

    days = [start_d + timedelta(days=i) for i in range((end_d - start_d).days + 1)]
    all_events: dict[str, dict] = {}
    calendar = []
    failures = 0
    with ThreadPoolExecutor(max_workers=6) as pool:
        for day, data in zip(days, pool.map(_safe_fetch_day, days)):
            if data is None:
                failures += 1
                continue
            for e in parse_events(data):
                all_events[e['id']] = e
            if not calendar:
                cal = data.get('leagues', [{}])[0].get('calendar', [])
                if cal:
                    calendar = cal

    if not all_events:
        raise ValueError(f'ESPN returned no games for this window ({failures}/{len(days)} day-queries failed)')
    with connect() as con:
        n_games = upsert_events(con, list(all_events.values()))
        n_weeks = upsert_weeks(con, season, calendar) if calendar else 0
    return {'games': n_games, 'weeks': n_weeks, 'days_queried': len(days), 'day_failures': failures}


def _safe_fetch_day(day: date):
    try:
        return _fetch_day(day)
    except Exception:
        return None


if __name__ == '__main__':
    import argparse
    from db.db import init_db
    p = argparse.ArgumentParser()
    p.add_argument('season', type=int)
    p.add_argument('--full-season', action='store_true')
    a = p.parse_args()
    init_db()
    print(ingest(a.season, full_season=True if a.full_season else False))
