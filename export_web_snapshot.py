"""Export a public snapshot for the read-only web companion (streamlit_app.py).

Run this manually, after using the desktop app (dashboard.py) at least once
this session so data/live.json is fresh:

    python export_web_snapshot.py

It writes data/web_snapshot.json -- small enough to commit to a public GitHub
repo (unlike live.json, which is 1.6MB+ and gitignored). It does NOT modify
dashboard.py, app.js, storage.py, or any other file the live server touches,
and it does not start or call the live server. It only reads:
  - data/live.json          (the cached season feed the desktop app writes)
  - data/picks.sqlite3      (your saved picks and closing-line archive, read-only)
  - data/nil.json, data/talent.json, data/penalties.json (refresh() caches,
    read/refreshed exactly like dashboard.add_power() does on every page load)
  - data/rank_history.json  (the poll-trend archive dashboard.py maintains)

The output is deliberately the *same shape* dashboard.py's /api/state sends
to app.js -- {"data": wire_data(payload), "picks": [...]} -- rather than a
reshaped/renamed subset. That lets the public site embed the real app.js
(as web_app.js, a read-only copy) unchanged and feed it this snapshot
directly as `state.data` / `state.picks`, with no adapter layer to maintain
in JavaScript. wire_data() is imported straight from dashboard.py (read-only
import; dashboard.py's server never starts unless its own __main__ runs) so
the two stay byte-for-byte in sync with zero duplicated logic.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import nil
import officiating
import power
import talent
from dashboard import wire_data
from storage import Store, settle

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
        payload.setdefault('warnings', []).append(f'Closing-line archive unavailable: {e}')
    spend = {}
    try:
        spend = nil.refresh(DATA)
        if spend.get('warning'):
            payload.setdefault('warnings', []).append(spend['warning'])
    except Exception as e:
        payload.setdefault('warnings', []).append(f'School spending unavailable: {e}')
    penalties = {}
    try:
        penalties = officiating.refresh(payload.get('history_events', []) + payload.get('events', []), DATA)
    except Exception as e:
        payload.setdefault('warnings', []).append(f'Penalty data unavailable: {e}')
    roster = {}
    try:
        roster = talent.refresh(DATA, payload.get('season'))
        if roster.get('warning'):
            payload.setdefault('warnings', []).append(roster['warning'])
    except Exception as e:
        payload.setdefault('warnings', []).append(f'Roster talent unavailable: {e}')
    try:
        payload['power'] = power.build(payload, date.today(), spend or None, penalties or None, roster or None)
    except Exception as e:
        payload['power'] = None
        payload.setdefault('warnings', []).append(f'Power ratings failed: {e}')
    try:
        payload['poll_trend'], payload['poll_history_weeks'] = poll_trend(payload, date.today(), DATA)
    except Exception as e:
        payload['poll_trend'], payload['poll_history_weeks'] = {}, 0
        payload.setdefault('warnings', []).append(f'Poll history unavailable: {e}')
    return payload


def main():
    cache = DATA / 'live.json'
    if not cache.exists():
        raise SystemExit('data/live.json is missing. Run the desktop app (Start Weekly Picks) at least once first.')
    payload = json.loads(cache.read_text(encoding='utf-8'))
    add_power(payload)

    store = Store(DATA / 'picks.sqlite3')
    try:
        rows = store.all()
    finally:
        store.db.close()
    for r in rows:
        r['result'], r['profit_units'] = settle(r)
    # Mirror dashboard.py's /api/state wire format exactly: drop the
    # provenance-only market_snapshot blob dashboard.py never sends either.
    picks = [{k: v for k, v in r.items() if k != 'market_snapshot'} for r in rows]

    # Trim to games that actually appear on the page (app.js's own render()
    # and renderPrint() apply this identical filter client-side, so this is a
    # pure size reduction, not a behavior change). Full event objects --
    # including every non-top50 game -- are kept for any team playing a
    # top-50 opponent this week, since app.js's previousGameBlock() searches
    # the *entire* events list (not just this week's) for a team's last game.
    events = payload.get('events', [])
    keep_ids = set()
    for e in events:
        if e.get('home_combined') or e.get('away_combined'):
            keep_ids.add(e.get('home_id'))
            keep_ids.add(e.get('away_id'))
    payload['events'] = [e for e in events if e.get('home_combined') or e.get('away_combined')
                          or e.get('home_id') in keep_ids or e.get('away_id') in keep_ids]

    # Same key set dashboard.py's /api/state sends as `data`: WIRE_OMIT drops
    # history_events/cbs/ap/coaches (raw poll/model inputs the page never
    # reads) and adds history_events_count in their place.
    data = wire_data(payload)

    # Mirror the remaining top-level fields dashboard.py's /api/state sends
    # that app.js's state object relies on (state.today feeds
    # previousGameBlock's "asOf" cutoff; refreshing/error drive the banner
    # text in render() -- both are always benign/false for a static export).
    snapshot = {'data': data, 'picks': picks, 'today': date.today().isoformat(),
                'refreshing': False, 'error': ''}

    out = DATA / 'web_snapshot.json'
    temp = out.with_suffix('.tmp')
    temp.write_text(json.dumps(snapshot, separators=(',', ':')), encoding='utf-8')
    temp.replace(out)
    print(f'Wrote {out} ({out.stat().st_size:,} bytes) with {len(snapshot["data"].get("events", []))} events '
          f'and {len(snapshot["picks"])} picks.')


if __name__ == '__main__':
    main()
