"""Export a slim public snapshot for the read-only web companion (streamlit_app.py).

Run this manually, after using the desktop app (dashboard.py) at least once
this session so data/live.json is fresh:

    python export_web_snapshot.py

It writes data/web_snapshot.json — small enough to commit to a public GitHub
repo (unlike live.json, which is 1.6MB+ and gitignored). It does NOT modify
dashboard.py, app.js, storage.py, or any other file the live server touches,
and it does not start or call the live server. It only reads:
  - data/live.json          (the cached season feed the desktop app writes)
  - data/picks.sqlite3      (your saved picks and closing-line archive, read-only)
  - data/nil.json, data/talent.json, data/penalties.json (refresh() caches,
    read/refreshed exactly like dashboard.add_power() does on every page load)
  - data/rank_history.json  (the poll-trend archive dashboard.py maintains)

The output aims to match everything a matchup card and the Power Ranking tab
render on the desktop page: market line/total, our lean and confidence, the
full "Model detail" breakdown (projected score, situational nudges, spending
and roster-talent priors, FCS-pooling note, weather note), rest/letdown/
lookahead notes, ATS records, weather alerts/forecasts, betting splits,
opponent offense/defense grades, and the combined Top-50/roster-cost/talent
tables. It intentionally still omits only truly internal plumbing (raw ESPN
odds-provider blobs, the officiating/penalty prior, which the desktop page
itself never displays) to keep the committed file reasonably small.
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


def restore_closing_lines(payload, store):
    """Give completed games back their pre-kickoff spread, same as dashboard.record_lines.

    ESPN strips the odds object once a game goes final, so without this every
    completed game would arrive with home_spread=None: ATS records would read
    zero forever and the letdown/lookahead notes (which need last week's
    spread) would never fire. Read-only: unlike the desktop app, this does not
    call store.capture_lines() first, so it never writes to picks.sqlite3 --
    it only reads whatever the desktop app has already archived.
    """
    try:
        closing = store.closing_lines()
    except Exception as e:
        print(f'Closing-line archive unavailable: {e}')
        return
    for e in payload.get('events', []):
        line = closing.get(e['id'])
        if e.get('completed') and e.get('home_spread') is None and line and line.get('home_spread') is not None:
            e['home_spread'] = line['home_spread']
            e['away_spread'] = -line['home_spread']
            e['home_odds'] = line.get('home_odds')
            e['away_odds'] = line.get('away_odds')
            e['total'] = line.get('total')
            e['closing_line_captured_at'] = line.get('captured_at')


def poll_trend(payload, today, data_dir):
    """Read-only version of dashboard.snapshot_and_trend: reports movement vs.
    the last archived week without writing a new entry to rank_history.json
    (that archive is maintained by the desktop app while it runs; writing to
    it here would duplicate that job outside of it, so this only reads it).
    """
    weeks = payload.get('weeks', [])
    current = next((w for w in weeks if w['start'][:10] <= today.isoformat() <= w['end'][:10]), None)
    path = data_dir / 'rank_history.json'
    try:
        history = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    except (OSError, ValueError):
        history = {}
    trend = {}
    if current and history:
        key = f"{payload.get('season')}-{current['type']}-{current['number']}"
        ordered = sorted(history, key=lambda k: tuple(int(x) for x in k.split('-')))
        # Prefer the week immediately before the current one when it's already
        # archived; otherwise fall back to the most recently archived week so
        # a snapshot taken before this week's own entry exists still shows
        # something rather than nothing.
        idx = ordered.index(key) if key in ordered else len(ordered)
        if idx > 0:
            prev_ranks = history[ordered[idx - 1]]['ranks']
            for t in payload.get('top50', []):
                prev = prev_ranks.get(t['id'])
                trend[t['id']] = 'new' if prev is None else prev - t['rank']
    return trend, len(history)


def add_power(payload):
    """Same augmentation dashboard.py's add_power() does, run standalone."""
    if not payload.get('events'):
        return payload
    try:
        store = Store(DATA / 'picks.sqlite3')
        try:
            restore_closing_lines(payload, store)
        finally:
            store.db.close()
    except Exception as e:
        print(f'Closing-line archive unavailable: {e}')
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
    try:
        payload['poll_trend'], payload['poll_history_weeks'] = poll_trend(payload, date.today(), DATA)
    except Exception as e:
        payload['poll_trend'], payload['poll_history_weeks'] = {}, 0
        print(f'Poll history unavailable: {e}')
    return payload


def team_grade(team_ratings_by_id, team_id):
    """Mirror app.js's grades(e,side): offense/defense rank+grade among rated FBS teams."""
    r = team_ratings_by_id.get(team_id)
    if not r:
        return None
    return {
        'ranked': r.get('ranked'),
        'offense_rank': r.get('offense_rank'), 'offense_grade': r.get('offense_grade'),
        'defense_rank': r.get('defense_rank'), 'defense_grade': r.get('defense_grade'),
        'games': r.get('games'),
        'ranking_population': r.get('ranking_population'), 'ranking_scope': r.get('ranking_scope'),
    }


def previous_game(all_events, team_id, game_date, as_of):
    """Mirror app.js's previousGameBlock: the team's last completed game before this one."""
    prior = [g for g in all_events if g.get('completed') and g.get('home_score') is not None and g.get('away_score') is not None
             and g['game_date'] < game_date and (not as_of or g['game_date'] < as_of)
             and (g.get('home_id') == team_id or g.get('away_id') == team_id)]
    if not prior:
        return None
    prior.sort(key=lambda g: g['game_date'], reverse=True)
    g = prior[0]
    own = 'home' if g.get('home_id') == team_id else 'away'
    other = 'away' if own == 'home' else 'home'
    scored, allowed = g.get(own + '_score'), g.get(other + '_score')
    result = 'Won' if scored > allowed else ('Lost' if scored < allowed else 'Tied')
    return {'game_date': g.get('game_date'), 'opponent': g.get(other), 'result': result,
            'scored': scored, 'allowed': allowed}


def venue_snapshot(e):
    v = e.get('venue') or {}
    address = v.get('address') or {}
    if not v and not address:
        return None
    return {'fullName': v.get('fullName'), 'indoor': v.get('indoor'),
            'city': address.get('city'), 'state': address.get('state')}


def event_snapshot(e, power_games, picks_by_event, all_events, team_ratings_by_id, as_of):
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
        'home_id': e.get('home_id'),
        'away_id': e.get('away_id'),
        'home_logo': e.get('home_logo'),
        'away_logo': e.get('away_logo'),
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
        'odds_status': e.get('odds_status'),
        'venue': venue_snapshot(e),
        'weather': e.get('weather'),
        'weather_status': e.get('weather_status'),
        'home_splits': e.get('home_splits'),
        'away_splits': e.get('away_splits'),
        # Headline lean/projection.
        'lean_side': p.get('lean_side'),
        'lean_home_spread': p.get('lean_home_spread'),
        'fair_home_spread': p.get('fair_home_spread'),
        'confidence': p.get('confidence'),
        'confidence_detail': p.get('confidence_detail'),
        'lean_result': p.get('lean_result'),
        'lean_source': p.get('lean_source'),
        'projected_total': p.get('projected_total'),
        'home_points': p.get('home_points'),
        'away_points': p.get('away_points'),
        'weather_alert': p.get('weather_alert'),
        'weather_note': p.get('weather_note'),
        # Full "Model detail" breakdown inputs.
        'home_edge_points': p.get('home_edge_points'),
        'lean_edge_points': p.get('lean_edge_points'),
        'total_edge_points': p.get('total_edge_points'),
        'spend_measure': p.get('spend_measure'),
        'spend_margin_shift': p.get('spend_margin_shift'),
        'home_spending': p.get('home_spending'),
        'away_spending': p.get('away_spending'),
        'home_talent': p.get('home_talent'),
        'away_talent': p.get('away_talent'),
        'talent_margin_shift': p.get('talent_margin_shift'),
        'pooled_fcs': p.get('pooled_fcs'),
        # Rest/letdown/lookahead/hostile-venue/rivalry notes and ATS records.
        'home_notes': p.get('home_notes'),
        'away_notes': p.get('away_notes'),
        'home_ats': p.get('home_ats'),
        'away_ats': p.get('away_ats'),
        'home_previous': previous_game(all_events, e.get('home_id'), e.get('game_date'), as_of),
        'away_previous': previous_game(all_events, e.get('away_id'), e.get('game_date'), as_of),
        # Opponent-adjusted offense/defense grades (app.js's grades()).
        'home_grade': team_grade(team_ratings_by_id, e.get('home_id')),
        'away_grade': team_grade(team_ratings_by_id, e.get('away_id')),
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
    team_ratings_by_id = {t['id']: t for t in power_data.get('team_ratings') or []}
    poll_trend_by_id = payload.get('poll_trend') or {}
    as_of = power_data.get('as_of')
    all_events = payload.get('events', [])
    events = [e for e in all_events if e.get('home_combined') or e.get('away_combined')]

    rankings = [
        {'rank': t.get('power_rank'), 'team': t.get('team'), 'id': t.get('id'), 'rating': t.get('rating'),
         'ap_rank': t.get('ap_rank'), 'combined_rank': t.get('combined_rank'), 'games': t.get('games'),
         'trend': t.get('trend'), 'poll_trend': poll_trend_by_id.get(t.get('id')),
         'offense_rank': t.get('offense_rank'), 'offense_grade': t.get('offense_grade'),
         'defense_rank': t.get('defense_rank'), 'defense_grade': t.get('defense_grade'),
         'ats': t.get('ats'), 'talent': t.get('talent'), 'spending': t.get('spending')}
        for t in sorted(power_data.get('ratings') or [], key=lambda r: r.get('power_rank') or 999)
    ]
    top50 = [{'rank': t.get('rank'), 'team': t.get('team'), 'id': t.get('id'), 'logo': t.get('logo'),
              'cbs': t.get('cbs'), 'ap': t.get('ap'), 'coaches': t.get('coaches')}
             for t in payload.get('top50', [])]

    power_meta = {
        'as_of': power_data.get('as_of'),
        'status': power_data.get('status'),
        'min_games': power_data.get('min_games'),
        'ranking_population': power_data.get('ranking_population'),
        'ranking_scope': power_data.get('ranking_scope'),
        'trend_since': power_data.get('trend_since'),
        'history_weeks_tracked': power_data.get('history_weeks_tracked'),
        'spend_fit': power_data.get('spend_fit'),
        'spend_board': power_data.get('spend_board'),
        'spend_labels': power_data.get('spend_labels'),
        'spend_source': power_data.get('spend_source'),
        'spend_fetched_at': power_data.get('spend_fetched_at'),
        'spend_fade_games': power_data.get('spend_fade_games'),
        'talent_fit': power_data.get('talent_fit'),
        'talent_board': power_data.get('talent_board'),
        'talent_source': power_data.get('talent_source'),
        'talent_fetched_at': power_data.get('talent_fetched_at'),
        'talent_fade_games': power_data.get('talent_fade_games'),
        'talent_max_weight': power_data.get('talent_max_weight'),
    }

    snapshot = {
        'season': payload.get('season'),
        'updated_at': payload.get('updated_at'),
        'weeks': payload.get('weeks', []),
        'events': [event_snapshot(e, power_games, picks_by_event, all_events, team_ratings_by_id, as_of) for e in events],
        'rankings': rankings,
        'top50': top50,
        'power_meta': power_meta,
        'poll_history_weeks': payload.get('poll_history_weeks', 0),
    }

    out = DATA / 'web_snapshot.json'
    temp = out.with_suffix('.tmp')
    temp.write_text(json.dumps(snapshot, separators=(',', ':')), encoding='utf-8')
    temp.replace(out)
    print(f'Wrote {out} ({out.stat().st_size:,} bytes) with {len(snapshot["events"])} matchups.')


if __name__ == '__main__':
    main()
