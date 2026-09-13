"""Export a slim public snapshot for the read-only web companion (streamlit_app.py).

Run this manually, after using the desktop app (dashboard.py) at least once
this session so data/live.json is fresh:

    python export_web_snapshot.py

It writes data/web_snapshot.json — small enough to commit to a public GitHub
repo (unlike live.json, which is 1.6MB+ and gitignored). It does NOT modify
dashboard.py, app.js, storage.py, or any other file the live server touches,
and it does not start or call the live server. It only reads:
  - data/live.json          (the cached season feed the desktop app writes)
  - data/picks.sqlite3      (your saved picks, read-only)
  - data/nil.json, data/talent.json, data/penalties.json (refresh() caches,
    read/refreshed exactly like dashboard.add_power() does on every page load)

The output contains only what the public Streamlit view needs: each Top-50
matchup this season (teams, market line, model lean/projection if available,
your saved pick side) and the combined poll rankings. It intentionally omits
raw feed internals (history_events, cbs/ap/coaches maps, weather payloads,
DraftKings split rows, venue objects) to keep the committed file small.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import nil
import officiating
import power
import talent
from storage import Store

FOLDER = Path(__file__).resolve().parent
DATA = FOLDER / 'data'


def add_power(payload):
    """Same augmentation dashboard.py's add_power() does, run standalone."""
    if not payload.get('events'):
        return payload
    spend = {}
    try:
        spend = nil.refresh(DATA)
    except Exception as e:
        print(f'School spending unavailable: {e}')
    penalties = {}
    try:
        penalties = officiating.refresh(payload.get('history_events', []) + payload.get('events', []), DATA)
    except Exception as e:
        print(f'Penalty data unavailable: {e}')
    roster = {}
    try:
        roster = talent.refresh(DATA, payload.get('season'))
    except Exception as e:
        print(f'Roster talent unavailable: {e}')
    try:
        payload['power'] = power.build(payload, date.today(), spend or None, penalties or None, roster or None)
    except Exception as e:
        payload['power'] = None
        print(f'Power ratings failed: {e}')
    return payload


def event_snapshot(e, power_games, picks_by_event):
    p = power_games.get(e['id']) or {}
    pick = picks_by_event.get(e['id'])
    return {
        'id': e['id'],
        'season': e.get('season'),
        'week': e.get('week'),
        'season_type': e.get('season_type'),
        'game_date': e.get('game_date'),
        'kickoff': e.get('kickoff'),
        'status': e.get('status'),
        'completed': e.get('completed'),
        'neutral': e.get('neutral'),
        'home': e.get('home'),
        'away': e.get('away'),
        'home_record': e.get('home_record'),
        'away_record': e.get('away_record'),
        'home_combined': e.get('home_combined'),
        'away_combined': e.get('away_combined'),
        'home_score': e.get('home_score'),
        'away_score': e.get('away_score'),
        'home_spread': e.get('home_spread'),
        'away_spread': e.get('away_spread'),
        'total': e.get('total'),
        'market_source': e.get('market_source'),
        'market_observed_at': e.get('market_observed_at'),
        'lean_side': p.get('lean_side'),
        'lean_home_spread': p.get('lean_home_spread'),
        'fair_home_spread': p.get('fair_home_spread'),
        'confidence': p.get('confidence'),
        'projected_total': p.get('projected_total'),
        'home_points': p.get('home_points'),
        'away_points': p.get('away_points'),
        'weather_alert': p.get('weather_alert'),
        'pick_side': pick.get('side') if pick else None,
        'pick_spread': pick.get('spread') if pick else None,
        'pick_favorite': bool(pick.get('favorite')) if pick else False,
    }


def main():
    cache = DATA / 'live.json'
    if not cache.exists():
        raise SystemExit('data/live.json is missing. Run the desktop app (Start Weekly Picks) at least once first.')
    payload = json.loads(cache.read_text(encoding='utf-8'))
    add_power(payload)

    store = Store(DATA / 'picks.sqlite3')
    try:
        picks = store.all()
    finally:
        store.db.close()
    picks_by_event = {r['event_id']: r for r in picks if r.get('event_id')}

    power_data = payload.get('power') or {}
    power_games = power_data.get('games') or {}
    events = [e for e in payload.get('events', []) if e.get('home_combined') or e.get('away_combined')]

    rankings = [
        {'rank': t.get('power_rank'), 'team': t.get('team'), 'rating': t.get('rating'),
         'ap_rank': t.get('ap_rank'), 'combined_rank': t.get('combined_rank'), 'games': t.get('games')}
        for t in sorted(power_data.get('ratings') or [], key=lambda r: r.get('power_rank') or 999)
    ]
    top50 = [{'rank': t.get('rank'), 'team': t.get('team')} for t in payload.get('top50', [])]

    snapshot = {
        'season': payload.get('season'),
        'updated_at': payload.get('updated_at'),
        'weeks': payload.get('weeks', []),
        'events': [event_snapshot(e, power_games, picks_by_event) for e in events],
        'rankings': rankings,
        'top50': top50,
    }

    out = DATA / 'web_snapshot.json'
    temp = out.with_suffix('.tmp')
    temp.write_text(json.dumps(snapshot, separators=(',', ':')), encoding='utf-8')
    temp.replace(out)
    print(f'Wrote {out} ({out.stat().st_size:,} bytes) with {len(snapshot["events"])} matchups.')


if __name__ == '__main__':
    main()
