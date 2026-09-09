from storage import Store, settle, summary
"""Personal weekly college football ATS pick tracker. No external packages."""
import csv
import math
import json
import queue
import threading
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

DATA = Path(__file__).resolve().parent / 'data'


def monday(day):
    return day-timedelta(days=day.weekday())








class App:
    def __init__(self, root, store):
        self.root, self.store = root, store
        self.week = monday(date.today())
        self.edit_id = None
        self.event_id = None
        self.market_snapshot = None
        self.events = []
        self.feed_queue = queue.Queue()
        self.fetching = False
        root.title('College Football • My Weekly ATS Picks')
        root.geometry('1250x900')
        root.minsize(1100, 800)
        style = ttk.Style()
        style.theme_use('clam')
        style.configure('Treeview', rowheight=29)
        style.configure('Title.TLabel', font=('Segoe UI', 19, 'bold'))
        body = ttk.Frame(root, padding=18)
        body.pack(fill='both', expand=True)
        ttk.Label(body, text='My College Football Picks', style='Title.TLabel').pack(anchor='w')
        ttk.Label(body, text='Select this week’s matchup, choose your side, and save your pick. Refresh imports lines and grades completed games.').pack(anchor='w', pady=(3, 14))
        nav = ttk.Frame(body)
        nav.pack(fill='x')
        ttk.Button(nav, text='‹ Previous week', command=lambda: self.move(-7)).pack(side='left')
        ttk.Button(nav, text='This week', command=self.today).pack(side='left', padx=6)
        ttk.Button(nav, text='Next week ›', command=lambda: self.move(7)).pack(side='left')
        self.week_label = ttk.Label(nav, font=('Segoe UI', 12, 'bold'))
        self.week_label.pack(side='left', padx=16)
        ttk.Button(nav, text='Backup database', command=self.backup).pack(side='right')
        ttk.Button(nav, text='Export all picks', command=self.export).pack(side='right', padx=6)
        feedbar = ttk.Frame(body)
        feedbar.pack(fill='x', pady=8)
        ttk.Button(feedbar, text='Refresh live data', command=self.fetch_live).pack(side='left')
        ttk.Button(feedbar, text='Import / refresh entire season', command=lambda: self.fetch_live(True)).pack(side='left', padx=6)
        self.filter = tk.StringVar(value='CBS Top 50')
        filters = ttk.Combobox(feedbar, textvariable=self.filter, values=['CBS Top 50', 'AP Top 25', 'All games'], state='readonly', width=16)
        filters.pack(side='left', padx=8)
        filters.bind('<<ComboboxSelected>>', lambda e: self.render_games())
        self.feed_status = ttk.Label(body, text='Loading saved schedule…')
        self.feed_status.pack(anchor='w')
        ttk.Label(body, text='Available matchups — double-click a row to prepare your pick').pack(anchor='w', pady=(7, 3))
        available = ttk.Frame(body)
        available.pack(fill='x')
        cols = ['date', 'matchup', 'ranks', 'line', 'splits', 'status']
        self.games_tree = ttk.Treeview(available, columns=cols, show='headings', height=6, selectmode='browse')
        for key, title, width in zip(cols, ['Kickoff (local)', 'Away @ Home', 'CBS / AP (away, home)', 'Home spread / odds', 'Home bets / handle', 'Status'], [130, 285, 170, 140, 150, 110]):
            self.games_tree.heading(key, text=title)
            self.games_tree.column(key, width=width)
        self.games_tree.pack(side='left', fill='x', expand=True)
        scroll = ttk.Scrollbar(available, orient='vertical', command=self.games_tree.yview)
        scroll.pack(side='right', fill='y')
        self.games_tree.configure(yscrollcommand=scroll.set)
        self.games_tree.bind('<Double-1>', self.choose_game)
        self.week_stats = ttk.Label(body)
        self.week_stats.pack(anchor='w', pady=(12, 3))
        self.all_stats = ttk.Label(body)
        self.all_stats.pack(anchor='w', pady=(0, 10))
        table = ttk.Frame(body)
        table.pack(fill='both', expand=True)
        columns = ('date', 'matchup', 'pick', 'odds', 'stake', 'score', 'result', 'net')
        self.tree = ttk.Treeview(table, columns=columns, show='headings', selectmode='browse', height=9)
        for c, title, width in zip(columns, ['Date', 'Away @ Home', 'Your ATS pick', 'Odds', 'Units risked', 'Final (away–home)', 'Result', 'Net units'], [95, 240, 190, 60, 80, 115, 75, 80]):
            self.tree.heading(c, text=title)
            self.tree.column(c, width=width, minwidth=50)
        scrollbar = ttk.Scrollbar(table, orient='vertical', command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.pack(side='left', fill='both', expand=True)
        scrollbar.pack(side='right', fill='y')
        self.tree.bind('<<TreeviewSelect>>', self.load)
        form = ttk.LabelFrame(body, text='Add a pick / select a saved row to edit or enter its final score', padding=12)
        form.pack(fill='x', pady=14)
        self.vars = {}
        fields = [('game_date', 'Game date (YYYY-MM-DD)'), ('away', 'Away school'), ('home', 'Home school'), ('side', 'Your picked side'), ('spread', 'Picked team spread'), ('odds', 'American odds'), ('stake', 'Units risked'), ('away_score', 'Away final score'), ('home_score', 'Home final score'), ('notes', 'Notes / reason for pick')]
        for i, (key, label) in enumerate(fields):
            row, col = divmod(i, 5)
            cell = ttk.Frame(form)
            cell.grid(row=row, column=col, sticky='ew', padx=5, pady=4)
            form.columnconfigure(col, weight=1)
            ttk.Label(cell, text=label).pack(anchor='w')
            v = self.vars[key] = tk.StringVar()
            widget = ttk.Combobox(cell, textvariable=v, values=['Home', 'Away'], state='readonly', width=16) if key == 'side' else ttk.Entry(cell, textvariable=v, width=20)
            widget.pack(fill='x', pady=(3, 0))
            if key == 'side':
                widget.bind('<<ComboboxSelected>>', self.fill_market)
        ttk.Label(form, text='Spread is for YOUR pick: favorite −7.5, underdog +7.5. Leave both final scores blank until the game ends.').grid(row=2, column=0, columnspan=5, sticky='w', pady=7)
        buttons = ttk.Frame(form)
        buttons.grid(row=3, column=0, columnspan=5, sticky='ew')
        self.save_button = ttk.Button(buttons, text='Save new pick', command=self.save)
        self.save_button.pack(side='left')
        ttk.Button(buttons, text='Clear / new pick', command=self.clear).pack(side='left', padx=8)
        self.status = ttk.Label(buttons)
        self.status.pack(side='left', padx=8)
        ttk.Label(body, text=f'Database: {DATA / "picks.sqlite3"}   •   Your saved spread is preserved when market lines refresh.').pack(anchor='w')
        self.clear()
        self.refresh()
        cache = DATA/'live.json'
        if cache.exists():
            try:
                payload = json.loads(cache.read_text(encoding='utf-8'))
                self.accept_feed(payload)
            except (ValueError, OSError):
                pass
        root.after(300, lambda: self.fetch_live(True))
        root.after(200, self.poll_feed)
        root.after(900000, self.periodic_refresh)

    def periodic_refresh(self):
        self.fetch_live()
        self.root.after(900000, self.periodic_refresh)

    def fetch_live(self, full=False):
        if self.fetching:
            return
        self.fetching = True
        self.feed_status.configure(text='Refreshing ESPN schedule, AP poll, CBS rankings and DraftKings splits…')
        week = self.week
        def work():
            try:
                from feeds import refresh
                self.feed_queue.put((True, refresh(DATA, week, full)))
            except Exception as e:
                self.feed_queue.put((False, str(e)))
        threading.Thread(target=work, daemon=True).start()

    def poll_feed(self):
        try:
            ok, result = self.feed_queue.get_nowait()
            self.fetching = False
            if ok:
                self.accept_feed(result)
            else:
                self.feed_status.configure(text='Refresh failed; saved data retained. '+result[:150])
        except queue.Empty:
            pass
        self.root.after(200, self.poll_feed)

    def accept_feed(self, payload):
        self.events = payload['events']
        self.store.apply_scores(self.events)
        message = f"Season {payload['season']} • {len(self.events)} cached events • Updated {payload['updated_at']}"
        if payload.get('warnings'):
            message += ' • '+ ' | '.join(payload['warnings'])
        self.feed_status.configure(text=message, wraplength=1180)
        self.render_games()
        self.refresh()

    def render_games(self):
        self.games_tree.delete(*self.games_tree.get_children())
        for e in self.events:
            if not self.week.isoformat() <= e['game_date'] <= (self.week+timedelta(days=6)).isoformat():
                continue
            if self.filter.get() == 'CBS Top 50' and min(e.get('home_cbs') or 999,e.get('away_cbs') or 999) > 50:
                continue
            if self.filter.get() == 'AP Top 25' and min(e.get('home_ap') or 999,e.get('away_ap') or 999) > 25:
                continue
            line = 'Unavailable' if e['home_spread'] is None else f"{e['home_spread']:+g} / {e['home_odds']:+g}" if e['home_odds'] is not None else f"{e['home_spread']:+g} / —"
            split = e.get('home_splits')
            splits = f"{split['bets']:g}% / {split['handle']:g}%" if split else '—'
            ranks = f"{e.get('away_cbs') or '—'},{e.get('home_cbs') or '—'} / {e.get('away_ap') or '—'},{e.get('home_ap') or '—'}"
            self.games_tree.insert('', 'end', iid=e['id'], values=(datetime.fromisoformat(e['kickoff']).strftime('%a %m/%d %I:%M%p'),f"{e['away']} @ {e['home']}",ranks,line,splits,e['status']))

    def choose_game(self, event=None):
        selected = self.games_tree.selection()
        if not selected:
            return
        e = next(e for e in self.events if e['id'] == selected[0])
        existing = next((r for r in self.store.all() if r.get('event_id') == e['id']), None)
        if existing:
            self.tree.selection_set(str(existing['id']))
            self.load()
            return
        self.clear()
        self.event_id = e['id']
        self.market_snapshot = json.dumps(e)
        for key in ('game_date', 'home', 'away', 'home_score', 'away_score'):
            self.vars[key].set('' if e.get(key) is None else str(e[key]))
        self.fill_market()
        self.status.configure(text=f"Source: {e['market_source'] or 'No line available'}")

    def fill_market(self, event=None):
        if self.event_id is None or self.edit_id is not None:
            return
        e = json.loads(self.market_snapshot)
        side = self.vars['side'].get().lower()
        for target, source in [('spread', side+'_spread'), ('odds', side+'_odds')]:
            self.vars[target].set('' if e.get(source) is None else str(e[source]))

    def move(self, days):
        self.week += timedelta(days=days)
        self.clear()
        self.refresh()
        self.render_games()
        self.fetch_live()

    def today(self):
        self.week = monday(date.today())
        self.clear()
        self.refresh()
        self.render_games()
        self.fetch_live()

    def clear(self):
        self.edit_id = None
        self.event_id = None
        self.market_snapshot = None
        default_date = date.today() if monday(date.today()) == self.week else self.week+timedelta(days=5)
        for key, v in self.vars.items():
            v.set({'game_date': default_date.isoformat(), 'side': 'Home', 'odds': '-110', 'stake': '1'}.get(key, ''))
        self.save_button.configure(text='Save new pick')
        self.status.configure(text='')
        self.tree.selection_remove(*self.tree.selection())

    def refresh(self):
        self.tree.delete(*self.tree.get_children())
        rows = self.store.all()
        weekly = [r for r in rows if self.week.isoformat() <= r['game_date'] <= (self.week+timedelta(days=6)).isoformat()]
        for r in weekly:
            result, profit = settle(r)
            team = r['home'] if r['side'] == 'Home' else r['away']
            score = '—' if result == 'Pending' else f"{r['away_score']}–{r['home_score']}"
            self.tree.insert('', 'end', iid=str(r['id']), values=(r['game_date'], f"{r['away']} @ {r['home']}", f"{team} {r['spread']:+g}", f"{r['odds']:+g}", f"{r['stake']:g}", score, result, '—' if result == 'Pending' else f'{profit:+.2f}'))
        self.week_label.configure(text=f'{self.week:%b %d, %Y} – {self.week+timedelta(days=6):%b %d, %Y}')
        self.week_stats.configure(text='This week: '+summary(weekly))
        self.all_stats.configure(text='All time: '+summary(rows))

    def load(self, event=None):
        selection = self.tree.selection()
        if not selection:
            return
        self.edit_id = int(selection[0])
        r = next(r for r in self.store.all() if r['id'] == self.edit_id)
        self.event_id = r.get('event_id')
        self.market_snapshot = r.get('market_snapshot')
        for key, v in self.vars.items():
            v.set('' if r[key] is None else str(r[key]))
        self.save_button.configure(text='Update selected pick')
        self.status.configure(text=f'Editing pick #{self.edit_id}')

    def save(self):
        try:
            v = {k: x.get().strip() for k, x in self.vars.items()}
            day = date.fromisoformat(v['game_date'])
            v['game_date'] = day.isoformat()
            if not v['home'] or not v['away'] or v['home'].casefold() == v['away'].casefold():
                raise ValueError('Enter two different school names.')
            if v['side'] not in ('Home', 'Away'):
                raise ValueError('Choose Home or Away.')
            for key in ('spread', 'odds', 'stake'):
                v[key] = float(v[key])
                if not math.isfinite(v[key]):
                    raise ValueError('Numbers must be finite.')
            if abs(v['odds']) < 100 or v['stake'] <= 0:
                raise ValueError('Odds must be ≤ −100 or ≥ +100. Units risked must be positive.')
            for key in ('home_score', 'away_score'):
                v[key] = int(v[key]) if v[key] else None
                if v[key] is not None and v[key] < 0:
                    raise ValueError('Final scores must be nonnegative whole numbers.')
            if (v['home_score'] is None) != (v['away_score'] is None):
                raise ValueError('Enter both final scores, or leave both blank.')
            if self.edit_id is None and any(r['game_date'] == v['game_date'] and r['home'].casefold() == v['home'].casefold() and r['away'].casefold() == v['away'].casefold() for r in self.store.all()):
                raise ValueError('A pick for this matchup is already saved. Select its row to update it.')
            v['event_id'] = self.event_id
            v['market_snapshot'] = self.market_snapshot
            self.store.save(v, self.edit_id)
            self.week = monday(day)
            self.clear()
            self.refresh()
            self.status.configure(text='Saved to your database.')
        except (ValueError, sqlite3.Error) as e:
            messagebox.showerror('Could not save pick', str(e))

    def export(self):
        path = filedialog.asksaveasfilename(title='Export all picks', defaultextension='.csv', initialfile='my_football_picks.csv', filetypes=[('CSV', '*.csv')])
        if not path:
            return
        try:
            rows = self.store.all()
            fields = ['id', 'game_date', 'home', 'away', 'side', 'spread', 'odds', 'stake', 'home_score', 'away_score', 'notes', 'created_at', 'updated_at', 'event_id', 'market_snapshot', 'result', 'profit_units']
            with open(path, 'w', newline='', encoding='utf-8-sig') as f:
                w = csv.DictWriter(f, fieldnames=fields)
                w.writeheader()
                for row in rows:
                    row['result'], row['profit_units'] = settle(row)
                    w.writerow(row)
            self.status.configure(text=f'Exported {len(rows)} picks.')
        except OSError as e:
            messagebox.showerror('Export failed', str(e))

    def backup(self):
        path = filedialog.asksaveasfilename(title='Backup picks database', defaultextension='.sqlite3', initialfile=f'picks-backup-{date.today()}.sqlite3')
        if path:
            try:
                if Path(path).resolve() == (DATA/'picks.sqlite3').resolve():
                    raise ValueError('Choose a different filename for your backup.')
                self.store.backup(path)
                self.status.configure(text='Database backup saved.')
            except (ValueError, OSError, sqlite3.Error) as e:
                messagebox.showerror('Backup failed', str(e))


def main():
    DATA.mkdir(exist_ok=True)
    store = Store(DATA/'picks.sqlite3')
    root = tk.Tk()
    App(root, store)
    root.mainloop()
    store.db.close()


if __name__ == '__main__':
    main()
