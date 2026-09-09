import sqlite3
import json
from datetime import datetime

def settle(pick):
    if pick['home_score'] is None or pick['away_score'] is None:
        return 'Pending', 0.
    margin = pick['home_score']-pick['away_score']
    adjusted = (margin if pick['side'] == 'Home' else -margin)+pick['spread']
    if adjusted == 0:
        return 'Push', 0.
    if adjusted < 0:
        return 'Loss', -pick['stake']
    odds = pick['odds']
    return 'Win', pick['stake']*(odds/100 if odds > 0 else 100/abs(odds))


class Store:
    def __init__(self, path):
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.execute('''CREATE TABLE IF NOT EXISTS picks (
            id INTEGER PRIMARY KEY, game_date TEXT NOT NULL, home TEXT NOT NULL,
            away TEXT NOT NULL, side TEXT NOT NULL, spread REAL NOT NULL,
            odds REAL NOT NULL, stake REAL NOT NULL, home_score INTEGER,
            away_score INTEGER, notes TEXT NOT NULL, created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL)''')
        self.db.commit()
        existing = {r[1] for r in self.db.execute('PRAGMA table_info(picks)')}
        for column in ('event_id', 'market_snapshot'):
            if column not in existing:
                self.db.execute(f'ALTER TABLE picks ADD COLUMN {column} TEXT')
        if 'favorite' not in existing:
            self.db.execute('ALTER TABLE picks ADD COLUMN favorite INTEGER NOT NULL DEFAULT 0')
        self.db.execute('CREATE TABLE IF NOT EXISTS pick_edits (id INTEGER PRIMARY KEY, pick_id INTEGER, prior_value TEXT, edited_at TEXT)')
        self.db.commit()

    def save(self, values, pick_id=None):
        now = datetime.now().astimezone().isoformat(timespec='seconds')
        columns = ['game_date', 'home', 'away', 'side', 'spread', 'odds', 'stake', 'home_score', 'away_score', 'notes', 'event_id', 'market_snapshot', 'favorite']
        values = dict(values)
        values.setdefault('event_id', None)
        values.setdefault('market_snapshot', None)
        values.setdefault('favorite', 0)
        with self.db:
            if pick_id is None:
                self.db.execute('INSERT INTO picks ('+','.join(columns)+',created_at,updated_at) VALUES ('+','.join('?' for _ in range(len(columns)+2))+')', [values[c] for c in columns]+[now, now])
            else:
                prior = self.db.execute('SELECT * FROM picks WHERE id=?', (pick_id,)).fetchone()
                if prior:
                    self.db.execute('INSERT INTO pick_edits (pick_id,prior_value,edited_at) VALUES (?,?,?)', (pick_id,json.dumps(dict(prior)),now))
                self.db.execute('UPDATE picks SET '+','.join(c+'=?' for c in columns)+',updated_at=? WHERE id=?', [values[c] for c in columns]+[now, pick_id])

    def apply_scores(self, events):
        finals = {e['id']: e for e in events if e['completed']}
        with self.db:
            for row in self.all():
                e = finals.get(row.get('event_id'))
                if e:
                    self.db.execute('UPDATE picks SET home_score=?,away_score=? WHERE id=?', (e['home_score'],e['away_score'],row['id']))

    def all(self):
        return [dict(r) for r in self.db.execute('SELECT * FROM picks ORDER BY game_date,id')]

    def set_favorite(self, pick_id, value):
        with self.db:
            cur = self.db.execute('UPDATE picks SET favorite=? WHERE id=?', (1 if value else 0, pick_id))
            if cur.rowcount == 0:
                raise ValueError('Saved pick not found')

    def backup(self, path):
        target = sqlite3.connect(path)
        try:
            self.db.backup(target)
        finally:
            target.close()


def summary(rows):
    counts = {k: 0 for k in ('Win', 'Loss', 'Push', 'Pending')}
    net, risk = 0., 0.
    for row in rows:
        result, profit = settle(row)
        counts[result] += 1
        net += profit
        if result != 'Pending':
            risk += row['stake']
    decisions = counts['Win']+counts['Loss']
    pct = f"{counts['Win']/decisions:.1%}" if decisions else '—'
    roi = f'{net/risk:.1%}' if risk else '—'
    return f"{counts['Win']} W / {counts['Loss']} L / {counts['Push']} Push • {counts['Pending']} pending • Win rate {pct} • Net {net:+.2f} units • ROI {roi}"


