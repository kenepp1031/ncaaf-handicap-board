"""Launch the Python pick tracker in a local browser. Data stays in SQLite."""
import json
import math
import os
import secrets
import socket
import threading
import webbrowser
from datetime import date, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs
from storage import Store, settle, summary
from feeds import refresh
import nil
import power
import servers

FOLDER = Path(__file__).resolve().parent
DATA = FOLDER/'data'
DATA.mkdir(exist_ok=True)
TOKEN = secrets.token_urlsafe(24)
LOCK = threading.Lock()
# Two counters let a poll answer "has anything changed?" with one integer
# comparison instead of shipping the whole season every five seconds. Bump
# them only while holding LOCK.
STATE = {'refreshing': False, 'error': '', 'data': {}, 'data_revision': 0, 'picks_revision': 0}
PENDING_SYNC = None


def publish(data):
    """Replace the published season data. LOCK must be held."""
    STATE['data'] = data
    STATE['data_revision'] += 1


def touch_picks():
    """Note that saved picks changed. LOCK must be held."""
    STATE['picks_revision'] += 1


# Keys the server needs and the page never reads. power.build takes cbs for the
# FBS pool (and so for FCS pooling), ap for the poll blend, and history_events
# for the fit; feeds keeps coaches as the fallback snapshot when the rankings
# call fails. history_events alone is ~766KB. Strip them here, at the
# serialization boundary, and never from STATE['data'] itself -- dropping any
# of them there degrades the model silently, with no error.
WIRE_OMIT = ('history_events', 'cbs', 'ap', 'coaches')


def wire_data(data):
    """The published season data as the page needs to see it."""
    if not data:
        return data
    wire = {key: value for key, value in data.items() if key not in WIRE_OMIT}
    wire['history_events_count'] = len(data.get('history_events') or ())
    return wire


def read_cache():
    cache = DATA/'live.json'
    return json.loads(cache.read_text(encoding='utf-8')) if cache.exists() else {}


def _week_key(season, w):
    return f"{season}-{w['type']}-{w['number']}"


def snapshot_and_trend(payload, today):
    """Record this week's combined Top 50 and report movement vs the last recorded week.

    ESPN's public rankings feed only ever returns the current poll (verified:
    the documented `week` parameter is ignored), so past weeks can't be
    backfilled automatically. This starts a local weekly archive in
    data/rank_history.json going forward — each week's entry keeps updating
    while that week is current, then freezes once the next week begins.
    """
    weeks = payload.get('weeks', [])
    current = next((w for w in weeks if w['start'][:10] <= today.isoformat() <= w['end'][:10]), None)
    path = DATA/'rank_history.json'
    history = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    if current:
        key = _week_key(payload['season'], current)
        history[key] = {'label': current['label'], 'captured_at': datetime.now().astimezone().isoformat(timespec='seconds'),
                         'ranks': {t['id']: t['rank'] for t in payload.get('top50', [])}}
        temp = path.with_suffix('.tmp')
        temp.write_text(json.dumps(history, indent=2), encoding='utf-8')
        temp.replace(path)
    trend = {}
    if current:
        key = _week_key(payload['season'], current)
        ordered = sorted(history, key=lambda k: tuple(int(x) for x in k.split('-')))
        idx = ordered.index(key)
        if idx > 0:
            prev_ranks = history[ordered[idx-1]]['ranks']
            for t in payload.get('top50', []):
                prev = prev_ranks.get(t['id'])
                trend[t['id']] = 'new' if prev is None else prev-t['rank']
    return trend, len(history)


def add_power(payload):
    if not payload.get('events'):
        return payload
    spend = {}
    try:
        spend = nil.refresh(DATA)
        if spend.get('warning'):
            payload.setdefault('warnings', []).append(spend['warning'])
    except Exception as e:
        payload.setdefault('warnings', []).append('School spending unavailable: '+str(e))
    try:
        payload['power'] = power.build(payload, date.today(), spend or None)
    except Exception as e:
        payload['power'] = None
        payload.setdefault('warnings', []).append('Power ratings failed: '+str(e))
    try:
        payload['poll_trend'], payload['poll_history_weeks'] = snapshot_and_trend(payload, date.today())
    except Exception as e:
        payload['poll_trend'], payload['poll_history_weeks'] = {}, 0
        payload.setdefault('warnings', []).append('Poll history tracking failed: '+str(e))
    return payload


def sync(full=False, week=None, week_end=None):
    global PENDING_SYNC
    with LOCK:
        if STATE['refreshing']:
            PENDING_SYNC = (full,week,week_end)
            return
        STATE['refreshing'] = True
        STATE['error'] = ''
    def worker():
        global PENDING_SYNC
        try:
            today = date.today()
            payload = refresh(DATA, week or today-timedelta(days=today.weekday()), full, week_end)
            add_power(payload)
            with LOCK:
                s = Store(DATA/'picks.sqlite3')
                try:
                    s.apply_scores(payload['events'])
                finally:
                    s.db.close()
                # Settled scores may have changed a pick's result.
                touch_picks()
                publish(payload)
        except Exception as e:
            with LOCK:
                STATE['error'] = str(e)
        finally:
            with LOCK:
                STATE['refreshing'] = False
                pending,PENDING_SYNC = PENDING_SYNC,None
            if pending:
                sync(*pending)
    threading.Thread(target=worker, daemon=True).start()


def validate_pick(body, prior, events):
    fields = ['game_date', 'home', 'away', 'side', 'spread', 'odds', 'stake', 'home_score', 'away_score', 'notes']
    v = {key: str(body.get(key, '')).strip() for key in fields}
    v['game_date'] = date.fromisoformat(v['game_date']).isoformat()
    if not v['home'] or not v['away'] or v['home'].casefold() == v['away'].casefold():
        raise ValueError('Enter two different school names.')
    if v['side'] not in ('Home', 'Away'):
        raise ValueError('Choose your side.')
    for key in ('spread', 'odds', 'stake'):
        v[key] = float(v[key])
        if not math.isfinite(v[key]):
            raise ValueError('Enter finite numbers.')
    if abs(v['odds']) < 100 or v['stake'] <= 0:
        raise ValueError('American odds must be at least +100 or at most -100; units must be positive.')
    for key in ('home_score', 'away_score'):
        v[key] = int(v[key]) if v[key] else None
        if v[key] is not None and v[key] < 0:
            raise ValueError('Scores must be nonnegative integers.')
    if (v['home_score'] is None) != (v['away_score'] is None):
        raise ValueError('Enter both final scores or leave both blank.')
    v['favorite'] = 1 if str(body.get('favorite', '')).strip().lower() in ('1', 'true', 'on') else 0
    event_id = prior.get('event_id') if prior else body.get('event_id')
    event = next((e for e in events if e['id'] == event_id), None)
    if event_id and not event:
        raise ValueError('Selected matchup is not in the saved schedule. Refresh first.')
    if event and (v['home'] != event['home'] or v['away'] != event['away']):
        raise ValueError('School names must match the selected event.')
    v['event_id'] = event_id
    v['market_snapshot'] = prior.get('market_snapshot') if prior else json.dumps(event) if event else None
    if event and event['completed']:
        v['home_score'], v['away_score'] = event['home_score'], event['away_score']
    return v


class LocalServer(ThreadingHTTPServer):
    allow_reuse_address = False

    def server_bind(self):
        if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


# Served without a token, exactly like '/' — the 127.0.0.1 bind and the Host
# check are the boundary, and a <script src> cannot send an auth header anyway.
# An explicit allow-list, never a path built from the request, so no traversal.
# The type must be exact: send() sets X-Content-Type-Options: nosniff, and a
# wrong type means the browser silently refuses to run the script.
STATIC = {'/app.js': ('app.js', 'text/javascript'),
          '/app.css': ('app.css', 'text/css')}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def send(self, data, status=200, kind='application/json'):
        content = data.encode('utf-8') if isinstance(data, str) else json.dumps(data).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', kind+'; charset=utf-8')
        self.send_header('Content-Length', str(len(content)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.end_headers()
        self.wfile.write(content)

    def allowed(self):
        return self.headers.get('Host') == f'127.0.0.1:{self.server.server_port}'

    def do_GET(self):
        if not self.allowed():
            return self.send({'error': 'Invalid host'}, 403)
        if self.path == '/':
            return self.send((FOLDER/'dashboard.html').read_text(encoding='utf-8').replace('__TOKEN__', TOKEN), kind='text/html')
        if self.path in STATIC:
            name, kind = STATIC[self.path]
            asset = FOLDER/name
            if not asset.exists():
                return self.send({'error': 'Not found'}, 404)
            return self.send(asset.read_text(encoding='utf-8'), kind=kind)
        if self.path == '/favicon.ico':
            icon = FOLDER/'cfb-icon.ico'
            if not icon.exists():
                return self.send({'error': 'Not found'}, 404)
            content = icon.read_bytes()
            self.send_response(200)
            self.send_header('Content-Type', 'image/x-icon')
            self.send_header('Content-Length', str(len(content)))
            self.send_header('Cache-Control', 'public, max-age=86400')
            self.end_headers()
            return self.wfile.write(content)
        if self.path == '/api/ping':
            return self.send({'app': servers.APP, 'port': self.server.server_port, 'pid': os.getpid()})
        if self.headers.get('X-Tracker-Token') != TOKEN:
            return self.send({'error': 'Unauthorized'}, 403)
        route, _, query = self.path.partition('?')
        if route == '/api/state':
            since = parse_qs(query).get('since', [''])[0]
            with LOCK:
                s = Store(DATA/'picks.sqlite3')
                try:
                    rows = s.all()
                finally:
                    s.db.close()
                body = {'data_revision': STATE['data_revision'], 'picks_revision': STATE['picks_revision'],
                        'refreshing': STATE['refreshing'], 'error': STATE['error']}
                # The season data is the expensive part and changes every 15
                # minutes at most, so send it only when the caller's copy is
                # stale. Taking a reference here is safe because publish()
                # replaces STATE['data'] wholesale and never mutates it.
                published = STATE['data'] if since != str(STATE['data_revision']) else None
            # Deliberately outside the lock: settle() is pure, and serializing
            # megabytes while holding it stalls the refresh worker behind every
            # poll. SQLite access stays inside — the worker writes that file.
            if published is not None:
                body['data'] = wire_data(published)
            for r in rows:
                r['result'], r['profit_units'] = settle(r)
            all_summary = summary(rows)
            # market_snapshot is the event as it looked when the pick was saved:
            # ~1.8KB each, kept in SQLite as provenance and never read by the
            # page. Dropping it from the wire alone is most of an idle poll.
            wire = [{k: v for k, v in r.items() if k != 'market_snapshot'} for r in rows]
            body.update(picks=wire, all_summary=all_summary, today=date.today().isoformat())
            self.send(body)
        else:
            self.send({'error':'Not found'},404)

    def do_POST(self):
        if not self.allowed() or self.headers.get('X-Tracker-Token') != TOKEN:
            return self.send({'error':'Unauthorized'},403)
        try:
            length = int(self.headers.get('Content-Length',0))
            if length > 100000:
                raise ValueError('Request too large')
            body = json.loads(self.rfile.read(length))
            if self.path == '/api/shutdown':
                self.send({'ok': True})
                threading.Thread(target=self.server.shutdown, daemon=True).start()
                return
            if self.path == '/api/refresh':
                sync(bool(body.get('full')), date.fromisoformat(body['week']),date.fromisoformat(body['week_end']) if body.get('week_end') else None)
                return self.send({'ok':True})
            if self.path == '/api/favorite':
                with LOCK:
                    s = Store(DATA/'picks.sqlite3')
                    try:
                        s.set_favorite(int(body['id']), bool(body.get('favorite')))
                    finally:
                        s.db.close()
                    touch_picks()
                return self.send({'ok':True})
            if self.path != '/api/save':
                return self.send({'error':'Not found'},404)
            with LOCK:
                s = Store(DATA/'picks.sqlite3')
                try:
                    rows = s.all()
                    pick_id = int(body['id']) if body.get('id') else None
                    prior = next((r for r in rows if r['id'] == pick_id), None)
                    if pick_id and not prior:
                        raise ValueError('Saved pick not found')
                    v = validate_pick(body, prior, STATE['data'].get('events',[]))
                    if not prior and any((v['event_id'] and r['event_id'] == v['event_id']) or (r['game_date'] == v['game_date'] and r['home'].casefold() == v['home'].casefold() and r['away'].casefold() == v['away'].casefold()) for r in rows):
                        raise ValueError('You already saved this matchup. Use Edit beside your pick.')
                    s.save(v, pick_id)
                finally:
                    s.db.close()
                touch_picks()
            self.send({'ok':True})
        except (ValueError, TypeError, KeyError) as e:
            self.send({'error':str(e)},400)
        except Exception as e:
            self.send({'error':str(e)},500)


def main():
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument('--no-browser',action='store_true')
    p.add_argument('--stop',action='store_true',help='close every running tracker server and exit')
    p.add_argument('--port',type=int,default=8768)
    a = p.parse_args()
    if a.stop:
        servers.stop_all(DATA, (a.port,))
        return
    running = servers.find_running(DATA, (a.port,))
    if running:
        if not a.no_browser:
            webbrowser.open(f'http://127.0.0.1:{running}')
        print(f'The tracker is already running: http://127.0.0.1:{running}', flush=True)
        return
    publish(add_power(read_cache()))
    try:
        server = LocalServer(('127.0.0.1', a.port), Handler)
    except OSError:
        if not a.no_browser:
            webbrowser.open(f'http://127.0.0.1:{a.port}')
        print('The tracker is already running or its port is occupied.', flush=True)
        return
    url = f'http://127.0.0.1:{server.server_port}'
    print('College football tracker:',url,flush=True)
    servers.register(DATA, server.server_port, TOKEN)
    sync(True)
    if not a.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        servers.deregister(DATA, server.server_port)
        server.server_close()


if __name__ == '__main__':
    main()
