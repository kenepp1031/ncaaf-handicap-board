"""Static dashboard.html generator: one page, one scroll. Everything is read
from SQLite once and baked into the page as inline HTML + CSS -- no template
engine, no client-side fetch. The week's Top-50 matchups are one list in
kickoff order.

There is deliberately no ranked pick list. The page used to lead with the five
biggest model-vs-market disagreements; walk-forward over 786 FBS-vs-FBS games
(2025-26) that is the model's worst bucket, not its best -- margin MAE 17.9 at
10+ points of disagreement against 10.7 inside a point, and 49-61 ATS in the
6-10 point band. Ranking games by disagreement was selecting for model error.
The lean still shows on each card, with a confidence label that now falls as
the model moves away from the market.
"""
from __future__ import annotations

import html
import json
import re
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common import normal
from db.db import connect
from ratings import injury_prior, manual, sharp_side
from ingest import transfers as transfers_ingest

OUT_PATH = Path(__file__).resolve().parent / "dashboard.html"

CSS = """
:root{--bg:#060a12;--panel:#0f1826;--panel-alt:#0b1420;--border:#1e2c42;--ink:#e7edf7;--muted:#7c8dab;
--muted2:#5c6c86;--accent:#2f8eff;--win:#35d488;--loss:#ff5c66;--note-bg:#2c2110;--note-fg:#f2b84b;
--weather-bg:#101f33;--weather-fg:#9fd0ff;--tag:#4fa8ff;--total:#bcd6ff;--header-row:#101b2c;--row-border:#1a2536}
*{box-sizing:border-box}html{background:var(--bg);scroll-behavior:smooth}
body{max-width:1440px;margin:auto;padding:28px;font-family:"Segoe UI",Arial,sans-serif;color:var(--ink);background:var(--bg)}
h1{margin:0;font-size:32px}h2{font-size:21px;margin:0 0 14px}p{color:var(--muted)}
header{display:flex;justify-content:space-between;align-items:center;margin-bottom:18px;gap:14px;flex-wrap:wrap}
.tag{font-size:12px;color:var(--tag);font-weight:700;letter-spacing:1.5px}
.card{background:var(--panel);border:1px solid var(--border);border-radius:12px;padding:20px;margin:16px 0}
small,.muted{color:var(--muted)}#source{font-size:13px;line-height:1.6}
a{color:var(--tag)}
table{width:100%;border-collapse:collapse;font-size:14px}
th{text-align:left;font-size:12px;color:var(--muted);background:var(--header-row);padding:12px 8px}
td{padding:12px 8px;border-bottom:1px solid var(--row-border)}
.scroll{overflow-x:auto}
.win{color:var(--win)}.loss{color:var(--loss)}.empty{text-align:center;padding:30px;color:var(--muted2)}
.tier-low{--tier:var(--muted)}.tier-moderate{--tier:var(--accent)}.tier-high{--tier:var(--win)}
.conf{display:inline-block;margin-top:4px;color:var(--tier);font-size:10px;font-weight:700;letter-spacing:.6px;text-transform:uppercase;padding:2px 8px;border:1px solid var(--tier);border-radius:4px;opacity:.85}
.conf b{font-size:12px}
.picks{display:flex;flex-direction:column;gap:6px}
.pick{display:flex;flex-wrap:wrap;align-items:baseline;gap:4px 12px;padding:10px 12px;border-radius:8px;background:var(--panel-alt);border:1px solid var(--border);border-left:3px solid var(--tier,var(--muted2));color:var(--ink);text-decoration:none;font-size:14px}
.pick:hover{border-color:var(--accent);border-left-color:var(--tier,var(--accent))}
.pick .n{color:var(--tag);font-weight:700}.pick .when{color:var(--muted);font-size:12px}.pick .conf{margin:0}
.match{display:grid;grid-template-columns:minmax(0,1fr) 260px minmax(0,1fr);gap:22px;padding:24px 20px;border-bottom:1px solid var(--row-border);align-items:center;scroll-margin-top:16px}
.match:nth-child(even){background:var(--panel-alt)}
.team-title{display:flex;align-items:center;gap:12px}.team-title img{width:46px;height:46px;object-fit:contain}
.team-title h3{font-size:21px;margin:4px 0}.rank{color:var(--tag);font-size:14px}
.team-sub{font-size:12px;color:var(--muted)}
.away{text-align:right}.away .team-title{justify-content:flex-end}
.stadium{font-size:12px;color:var(--muted2);margin:12px 0 6px;line-height:1.7}
.weather{display:inline-block;font-size:12px;background:var(--weather-bg);color:var(--weather-fg);padding:7px 9px;border-radius:5px;line-height:1.6}
.weather small{font-size:10px}
.market{text-align:center}.kickoff{font-size:12px;color:var(--muted);margin-bottom:9px}.kickoff b{color:var(--ink)}
.total{font-size:13px;font-weight:700;margin-bottom:9px;color:var(--total)}
.market-source{font-size:10px;color:var(--muted2);margin-top:8px}
.split{margin-top:10px;text-align:left}
.split-label{font-size:9px;font-weight:700;letter-spacing:.6px;text-transform:uppercase;color:var(--muted2);text-align:center;margin-bottom:4px}
.split-row{display:grid;grid-template-columns:34px 1fr 34px;gap:6px;align-items:center;margin-top:5px;font-size:11px;position:relative}
.split-row b{color:var(--ink)}.split-row .r{text-align:right}
.split-row span{grid-column:2;font-size:9px;text-transform:uppercase;letter-spacing:.5px;color:var(--muted2);text-align:center;margin-top:1px}
.split-bar{display:flex;gap:2px;height:8px;border-radius:4px;overflow:hidden;background:var(--row-border)}
.split-bar i{display:block;height:100%;border-radius:4px}
.money-tag{margin-top:6px;font-size:11px;color:var(--muted);text-align:center}.money-tag b{color:var(--ink)}
.money-tag em{font-style:normal;font-size:9px;font-weight:700;letter-spacing:.6px;text-transform:uppercase;padding:2px 6px;border-radius:4px;margin-right:4px}
.mt-sharp{background:#10301f;color:var(--win)}.mt-big{background:var(--row-border);color:var(--total)}.mt-whale{background:#0f2a4a;color:var(--weather-fg)}.mt-loaded{background:var(--note-bg);color:var(--note-fg)}
details summary{cursor:pointer;font-weight:600}
.notes{margin-top:8px;display:flex;gap:4px;flex-wrap:wrap}
.note{display:inline-block;font-size:10px;background:var(--note-bg);color:var(--note-fg);padding:3px 7px;border-radius:4px;margin:2px 0 0}
.away .notes{justify-content:flex-end}
.model-detail{font-size:11px;color:var(--muted);text-align:left;margin:9px 0 2px;border-top:1px dashed var(--border);padding-top:7px;line-height:1.7}
.model-detail summary{font-size:10px;font-weight:700;letter-spacing:.6px;text-transform:uppercase;color:var(--muted2);text-align:center}
.model-detail>div{margin-top:6px}.model-detail b{color:var(--ink)}.model-detail small{display:block;color:var(--muted2);font-size:10px}
.weather-alert{grid-column:1/-1;background:var(--loss);color:#fff;font-weight:700;font-size:13px;padding:9px 14px;border-radius:6px;margin-bottom:14px}
.grades{font-size:13px;line-height:1.7;margin:10px 0}.grades b{color:var(--tag)}.grades small{display:block;color:var(--muted);font-size:10px}
.yardage{font-size:11px;color:var(--muted);line-height:1.7;margin:-4px 0 10px}.yardage b{color:var(--ink)}.yardage i{font-style:normal;color:var(--muted2)}
.yardage small{display:block;color:var(--muted2);font-size:10px}
.note.qb{background:#2a1430;color:#f0a8ff}
.note.qbout{background:#3a1216;color:#ff9aa2}
.roster{font-size:11px;color:var(--muted);line-height:1.7;margin:-4px 0 10px}.roster b{color:var(--ink)}.roster i{font-style:normal;color:var(--muted2)}
.roster .out{color:var(--loss)}.roster .q{color:var(--note-fg)}.roster small{display:block;color:var(--muted2);font-size:10px}
.away .roster{text-align:right}
.sharp td b{color:var(--ink)}.sharp .strong td:nth-child(2){color:var(--win);font-weight:700}
.sharp .done{opacity:.75}.sharp-rec{font-size:13px;color:var(--muted);margin:-6px 0 12px;line-height:1.7}.sharp-rec b{color:var(--ink)}
.model-lean{font-size:13px;margin:8px 0;line-height:1.6}
.projection{font-size:11px;color:var(--muted);margin:8px 0 10px;line-height:1.7}.projection b{color:var(--ink)}
.projected-score{font-size:10px;margin-top:4px}
@media(max-width:850px){body{padding:12px}header{display:block}.card{padding:14px}.match{grid-template-columns:minmax(0,1fr) 175px minmax(0,1fr);gap:8px;padding:18px 5px}.team-title{display:block}.away .team-title img{float:right}.team-title h3{font-size:16px}.team-title img{width:34px;height:34px}.stadium{font-size:11px}}
@media(max-width:550px){.match{grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:10px}.weather-alert{order:-2}.market{grid-column:1/-1;order:-1;padding-bottom:10px;border-bottom:1px dashed var(--border)}.team-title h3{font-size:15px}.weather{padding:4px 6px}}
"""


def esc(s) -> str:
    return html.escape(str(s)) if s is not None else ''


def half(n):
    return '—' if n is None else f'{round(float(n) * 2) / 2:.1f}'


def spread_text(n):
    if n is None:
        return '—'
    return ('+' if n > 0 else '') + half(n)


def side_spread(g, side):
    """Market spread from one side's point of view. Only home_spread is kept
    current by every line source, so derive the away number from it."""
    if g['home_spread'] is None:
        return None
    return g['home_spread'] if side == 'home' else -g['home_spread']


def time_label(iso):
    """'1:00 PM Saturday' in this machine's local time zone, from any ISO timestamp with an offset."""
    try:
        dt = datetime.fromisoformat(iso).astimezone()
    except (TypeError, ValueError):
        return iso or 'Time TBD'
    return f"{dt.strftime('%I:%M %p').lstrip('0')} {dt.strftime('%A')}"


def trend_text(v):
    if v is None:
        return '—'
    if v == 'new':
        return 'NEW'
    v = int(v)
    if v == 0:
        return '–'
    return f'▲{v}' if v > 0 else f'▼{abs(v)}'


def trend_class(v):
    if v is None or v == 'new':
        return ''
    v = int(v)
    return 'win' if v > 0 else ('loss' if v < 0 else '')


def team_title(g, side):
    name = g[f'{side}_name']
    logo = g[f'{side}_logo'] or ''
    rank = g[f'{side}_combined']
    sub = ('DESIGNATED HOME · NEUTRAL SITE' if g['neutral'] else 'HOME') if side == 'home' else 'AWAY'
    img = f'<img src="{esc(logo)}" alt="" loading="lazy">' if logo else ''
    rank_html = f'<span class="rank" title="Combined CBS / AP / Coaches poll">Poll #{rank}</span> ' if rank else ''
    return f'<div class="team-title">{img}<div><div class="team-sub">{esc(sub)}</div><h3>{rank_html}{esc(name)}</h3></div></div>'


def grades_block(rating_row, season_games=0):
    if rating_row is None:
        return '<div class="grades">Outside FBS ranking pool<small>Not assigned an FBS rank or grade</small></div>'
    off = f"#{rating_row['offense_rank']} · {rating_row['offense_grade']}" if rating_row['offense_rank'] else 'Unrated'
    dfn = f"#{rating_row['defense_rank']} · {rating_row['defense_grade']}" if rating_row['defense_rank'] else 'Unrated'
    pop = rating_row['ranking_population'] or '—'
    scope = rating_row['ranking_scope'] or 'FBS'
    games = rating_row['games'] or 0
    basis = f'{season_games} games this season · {games} in the fit'
    provisional = ' · mostly last season' if season_games < 4 else ''
    return (f'<div class="grades">Offense <b>{off}</b><br>Defense <b>{dfn}</b>'
            f'<small>Out of {pop} {esc(scope)} teams · {basis}{provisional}</small></div>')


def notes_block(notes):
    if not notes:
        return ''
    def cls(n):
        if n.startswith('QB out'):
            return ' qbout'
        if n.startswith('QB '):
            return ' qb'
        return ''
    pills = ''.join(f'<span class="note{cls(n)}">{esc(n)}</span>' for n in notes)
    return f'<div class="notes">{pills}</div>'


def season_plays(con, season):
    """Per-team per-game efficiency from play_stats (garbage time stripped), with the
    opponent's numbers from the same game as the 'allowed' side."""
    rows = con.execute(
        """SELECT p.*, g.game_date FROM play_stats p JOIN games g USING(game_id)
           WHERE g.season=? AND g.completed=1""", (season,)).fetchall()
    by_game = {}
    for r in rows:
        by_game.setdefault(r['game_id'], {})[r['side']] = dict(r)
    logs = {}
    for sides in by_game.values():
        if len(sides) != 2:
            continue
        for side, other in (('home', 'away'), ('away', 'home')):
            me, opp = sides[side], sides[other]
            logs.setdefault(me['team_id'], []).append({'me': me, 'opp': opp})
    return logs


def efficiency_summary(log):
    if not log:
        return None
    def rate(key, num, den):
        n = sum(x[key][num] or 0 for x in log)
        d = sum(x[key][den] or 0 for x in log)
        return n / d if d else None
    return {'games': len(log),
            'sr': rate('me', 'successes_ng', 'plays_ng'), 'sr_allowed': rate('opp', 'successes_ng', 'plays_ng'),
            'ypp': rate('me', 'yards_ng', 'plays_ng'), 'ypp_allowed': rate('opp', 'yards_ng', 'plays_ng'),
            'expl': rate('me', 'explosives_ng', 'plays_ng'), 'expl_allowed': rate('opp', 'explosives_ng', 'plays_ng'),
            'ppd': rate('me', 'drive_points', 'drives'), 'ppd_allowed': rate('opp', 'drive_points', 'drives')}


def efficiency_ranks(summaries, fbs_ids):
    pool = {t: s for t, s in summaries.items() if t in fbs_ids and s}
    ranks = {t: {} for t in pool}
    for key, best_high in (('sr', True), ('sr_allowed', False), ('ypp', True), ('ypp_allowed', False),
                           ('expl', True), ('expl_allowed', False), ('ppd', True), ('ppd_allowed', False)):
        values = [s[key] for s in pool.values() if s[key] is not None]
        for t, s in pool.items():
            if s[key] is not None:
                ranks[t][key] = 1 + sum(v > s[key] if best_high else v < s[key] for v in values)
    return ranks, len(pool)


def efficiency_block(summary, ranks, population):
    """Per-play quality, garbage time removed. Display only: walk-forward on 2026-10-02
    an efficiency training target did not beat the final score (README)."""
    if not summary or summary['sr'] is None:
        return ''

    def rk(key):
        r = ranks.get(key)
        return f' <i>#{r}</i>' if r else ''

    def pct(v):
        return '—' if v is None else f'{100 * v:.0f}%'

    return (f'<div class="yardage">Success rate <b>{pct(summary["sr"])}</b>{rk("sr")} · '
            f'allowed <b>{pct(summary["sr_allowed"])}</b>{rk("sr_allowed")}<br>'
            f'Explosive plays <b>{pct(summary["expl"])}</b>{rk("expl")} · '
            f'allowed <b>{pct(summary["expl_allowed"])}</b>{rk("expl_allowed")}<br>'
            f'Points/drive <b>{summary["ppd"]:.2f}</b>{rk("ppd")} · '
            f'allowed <b>{summary["ppd_allowed"]:.2f}</b>{rk("ppd_allowed")}'
            f'<small>Per play, garbage time removed · {summary["games"]} games'
            f'{f" · # = rank of {population} FBS" if ranks else ""}</small></div>')


def injuries_by_team(con):
    out = {}
    for r in con.execute('SELECT * FROM injuries ORDER BY CASE status WHEN "Out" THEN 0 WHEN "Doubtful" THEN 1 ELSE 2 END, pos'):
        out.setdefault(r['team_id'], []).append(dict(r))
    return out


def roster_block(team_injuries, portal, qb_hit):
    """Who is hurt (covers.com) and what the portal did to the roster (247Sports)."""
    parts = []
    if team_injuries:
        out = [i for i in team_injuries if (i['status'] or '').lower() in ('out', 'doubtful', 'out for season', 'injured reserve')]
        quest = [i for i in team_injuries if i not in out]

        def names(items, limit=4):
            shown = ', '.join(f"{esc(i['pos'])} {esc(i['player'])}" for i in items[:limit])
            return shown + (f' +{len(items) - limit} more' if len(items) > limit else '')
        line = []
        if out:
            line.append(f'<span class="out">Out/doubtful {len(out)}</span>: {names(out)}')
        if quest:
            line.append(f'<span class="q">Questionable {len(quest)}</span>: {names(quest, 3)}')
        title = ' | '.join(f"{i['player']} ({i['pos']}) {i['status']}{(' - ' + i['injury']) if i['injury'] else ''}" for i in team_injuries)
        parts.append(f'<div title="{esc(title)}">{" · ".join(line)}</div>')
    if portal:
        def top(items):
            return ', '.join(f"{esc(x['pos'])} {esc(x['player'])} {x['rating']:.2f}" for x in items)
        title = f"In: {top(portal['in_top'])} | Out: {top(portal['out_top'])}"
        net = portal['net_rating']
        net_cls = 'win' if net > 0.5 else ('loss' if net < -0.5 else '')
        parts.append(f'<div title="{esc(title)}">Portal <b>{portal["in_n"]} in</b>'
                     f'{f" (avg {portal['in_avg']:.2f})" if portal["in_avg"] else ""} · <b>{portal["out_n"]} out</b>'
                     f'{f" (avg {portal['out_avg']:.2f})" if portal["out_avg"] else ""} · net <b class="{net_cls}">{net:+.1f}</b></div>')
    if not parts:
        return ''
    foot = ('Injuries from covers.com; portal from 247Sports (net = rating weight above 0.80 gained minus lost). '
            'Only a starting QB listed Out or Doubtful moves the number.')
    return f'<div class="roster">{"".join(parts)}<small>{foot}</small></div>'


def season_box(con, season):
    """Per-team game log from box_scores for this season, oldest first. Context only --
    walk-forward (2026-09-26) found yards per play and turnovers added nothing to the
    model's margin projections, so none of this feeds the rating."""
    rows = con.execute(
        """SELECT b.game_id, b.side, b.team_id, b.plays, b.total_yards, b.turnovers, b.qb_id, b.qb_name,
                  g.game_date, g.home_id, g.away_id
           FROM box_scores b JOIN games g USING(game_id) WHERE g.season=? AND g.completed=1""", (season,)).fetchall()
    by_game = {}
    for r in rows:
        by_game.setdefault(r['game_id'], {})[r['side']] = dict(r)
    logs = {}
    for sides in by_game.values():
        if len(sides) != 2:
            continue
        for side, other in (('home', 'away'), ('away', 'home')):
            me, opp = sides[side], sides[other]
            logs.setdefault(me['team_id'], []).append({
                'date': me['game_date'], 'opp_id': opp['team_id'], 'yards': me['total_yards'], 'plays': me['plays'],
                'yards_allowed': opp['total_yards'], 'plays_allowed': opp['plays'],
                'lost': me['turnovers'], 'gained': opp['turnovers'], 'qb_id': me['qb_id'], 'qb_name': me['qb_name']})
    for log in logs.values():
        log.sort(key=lambda x: x['date'])
    return logs


def _ratio(log, num, den):
    n = sum(x[num] for x in log if x[num] is not None and x[den])
    d = sum(x[den] for x in log if x[num] is not None and x[den])
    return n / d if d else None


def yardage_summary(log):
    if not log:
        return None
    games = [x for x in log if x['yards'] is not None and x['yards_allowed'] is not None]
    if not games:
        return None
    return {'games': len(games),
            'ypg': sum(x['yards'] for x in games) / len(games),
            'ypg_allowed': sum(x['yards_allowed'] for x in games) / len(games),
            'ypp': _ratio(games, 'yards', 'plays'), 'ypp_allowed': _ratio(games, 'yards_allowed', 'plays_allowed'),
            'gained': sum(x['gained'] or 0 for x in games), 'lost': sum(x['lost'] or 0 for x in games)}


def yardage_ranks(summaries, fbs_ids):
    """FBS rank for each stat; 1 = best (most yards gained, fewest allowed)."""
    pool = {t: s for t, s in summaries.items() if t in fbs_ids and s}
    ranks = {t: {} for t in pool}
    for key, best_high in (('ypg', True), ('ypg_allowed', False), ('ypp', True), ('ypp_allowed', False)):
        values = [s[key] for s in pool.values() if s[key] is not None]
        for t, s in pool.items():
            if s[key] is not None:
                ranks[t][key] = 1 + sum(v > s[key] if best_high else v < s[key] for v in values)
    return ranks, len(pool)


def yardage_block(summary, ranks, population):
    if not summary:
        return ''

    def rk(key):
        r = ranks.get(key)
        return f' <i>#{r}</i>' if r else ''

    def num(v, fmt):
        return '—' if v is None else format(v, fmt)

    margin = summary['gained'] - summary['lost']
    margin_text = ('+' if margin > 0 else '') + str(margin)
    return (f'<div class="yardage">Yards/game <b>{num(summary["ypg"], ".0f")}</b>{rk("ypg")} · '
            f'allowed <b>{num(summary["ypg_allowed"], ".0f")}</b>{rk("ypg_allowed")}<br>'
            f'Yards/play <b>{num(summary["ypp"], ".1f")}</b>{rk("ypp")} · '
            f'allowed <b>{num(summary["ypp_allowed"], ".1f")}</b>{rk("ypp_allowed")}<br>'
            f'Turnovers <b>{margin_text}</b> ({summary["gained"]} forced, {summary["lost"]} lost)'
            f'<small>{summary["games"]} games this season · raw, not opponent-adjusted'
            f'{f" · # = rank of {population} FBS" if ranks else ""}</small></div>')


def qb_change_note(log, before_date, team_names):
    """Pre-kickoff read: did the team's most recent game have a different starter than
    the QB who started most of its games before that? Starter = most pass attempts."""
    prior = [x for x in (log or []) if x['date'] < before_date and x['qb_id']]
    if len(prior) < 2:
        return None
    last, earlier = prior[-1], prior[:-1]
    counts = {}
    for x in earlier:
        counts[x['qb_id']] = counts.get(x['qb_id'], 0) + 1
    primary = max(counts, key=lambda q: (counts[q], max(i for i, x in enumerate(earlier) if x['qb_id'] == q)))
    if last['qb_id'] == primary:
        return None
    primary_name = next(x['qb_name'] for x in earlier if x['qb_id'] == primary)
    opp = team_names.get(last['opp_id'], 'last opponent')
    return (f"QB change: {last['qb_name']} started last game (vs {opp}) — "
            f"{primary_name} had started {counts[primary]} of {len(earlier)} before that")


def weather_text(w, indoor):
    if indoor:
        return '<span class="weather">Indoor venue · field conditions sheltered</span>'
    if not w or w['status'] != 'Kickoff through approximately 3 hours after kickoff':
        status = w['status'] if w else 'Game forecast unavailable'
        return f'<span class="weather">{esc(status)}</span>'
    return (f'<span class="weather"><b>{round(w["temp_f"])}°F</b>, wind {round(w["wind_mph"] or 0)} mph'
            f'<br><small>updated {esc(time_label(w["checked_at"]))}</small></span>')


def weather_alert_block(w):
    if not w or not w['alert_text']:
        return ''
    return f'<div class="weather-alert">⚠️ {esc(w["alert_text"])}</div>'


def model_detail(g, proj):
    if not proj or proj['lean_source'] != 'model':
        return ''

    def toward(n):
        if n is None:
            return None
        if n == 0:
            return 'even with the market'
        return f'{half(abs(n))} pts toward ' + esc(g['home_name'] if n > 0 else g['away_name'])

    rows = []
    raw = toward(proj['home_edge_points'])
    if raw:
        rows.append(f'<div>Model line vs market: <b>{raw}</b></div>')
    nudge = None
    if proj['fair_home_spread'] is not None and proj['lean_home_spread'] is not None:
        nudge = proj['fair_home_spread'] - proj['lean_home_spread']
    if nudge is not None and abs(nudge) >= 0.5:
        rows.append(f'<div>Situational adjustment: <b>{toward(nudge)}</b>'
                    f'<small>Rest, letdown and lookahead notes shown beside each team.</small></div>')
    used = toward(proj['lean_edge_points'])
    if used:
        rows.append(f'<div>Edge behind the lean: <b>{used}</b>'
                    f'<small>Needs 1.0 pt for any lean. Confidence falls as this gap grows: '
                    f'High under 3.0 pts, Moderate under 6.0, Low beyond that — and Low for '
                    f'either team under two games this season.</small></div>')
    if proj['projected_total'] is not None:
        gap = proj['total_edge_points']
        compared = 'no market total to compare' if gap is None else f"{half(abs(gap))} pts {'above' if gap >= 0 else 'below'} the market"
        rows.append(f'<div>Projected total: <b>{half(proj["projected_total"])}</b> · {compared}'
                    f'<small>Context only — this app makes no Over/Under picks.</small></div>')
    if proj['spend_margin_shift'] is not None:
        effect = toward(proj['spend_margin_shift']) if proj['spend_margin_shift'] else 'no adjustment left — both teams have enough games this season'
        rows.append(f'<div>Spending prior: <b>{effect}</b></div>')
    if proj['talent_margin_shift'] is not None:
        effect = toward(proj['talent_margin_shift']) if abs(proj['talent_margin_shift'] or 0) >= 0.25 else 'under half a point'
        rows.append(f'<div>Roster talent prior: <b>{effect}</b></div>')
    qb = proj.get('injury_margin_shift') or 0
    if qb:
        rows.append(f'<div>Starting QB out: <b>{toward(qb)}</b>'
                    f'<small>covers.com lists the starter Out or Doubtful. A fixed prior of {injury_prior.QB_OUT_POINTS:g} pts '
                    f'(half if the backup already started last game); graded with and without it.</small></div>')
    hand = proj.get('manual_margin_shift') or 0
    if hand:
        rows.append(f'<div>Your adjustment: <b>{toward(hand)}</b>'
                    f'<small>From manual_adjustments.csv. The record is graded with and without it.</small></div>')
    pooled = json.loads(proj['pooled_fcs_json']) if proj.get('pooled_fcs_json') else []
    if pooled:
        who = ' and '.join(esc(g[f'{s}_name']) for s in pooled)
        rows.append(f'<div>FCS opponent: <b>{who}</b><small>Rated as a pooled FCS baseline, not individually. '
                    f'One or two games against FBS teams cannot rate a school on its own.</small></div>')
    if proj['confidence_detail']:
        rows.append(f'<div><small>{esc(proj["confidence_detail"])}</small></div>')
    return f'<details class="model-detail"><summary>Model detail</summary>{"".join(rows)}</details>' if rows else ''


def lean_text(g, proj):
    side = (proj.get('lean_side') or '').lower() if proj else ''
    if not side:
        return None
    return esc(g[f'{side}_name']) + ' ' + spread_text(side_spread(g, side))


def confidence_html(proj):
    tier = proj.get('confidence') if proj else None
    rating = confidence_rating(proj) if proj and proj.get('lean_side') else None
    if rating is None:
        return f'<small>Confidence: {esc(tier or "Unavailable")}</small>'
    return f'<small class="conf tier-{tier.lower()}">{esc(tier)} · <b>{rating}</b>/10</small>'


def lean_line(g, proj):
    text = lean_text(g, proj) or 'No lean'
    return f'<div class="model-lean">Our lean: <b>{text}</b><br>{confidence_html(proj)}</div>'


SHARP_GAP = 20      # money % this far above ticket % = bigger bettors on that side
WHALE_GAP = 30      # ...this far above, on a side the public isn't on = a few very large bets
WHALE_MAX_BETS = 35
LOADED_JUMP = 8     # money % up this much since the last refresh while tickets barely moved
LINE_CONFIRM = 0.5  # spread moved at least this far toward the side since the first capture


def line_note(line_move):
    """How the spread has moved for this side since the first capture (positive = their way)."""
    if line_move is None:
        return ''
    if line_move >= LINE_CONFIRM:
        return f' · ✅ line moved {line_move:g} their way'
    if line_move <= -LINE_CONFIRM:
        return f' · ⚠️ line moved {-line_move:g} against them'
    return ' · line hasn’t moved'


def money_tags(split, line_move=None):
    """Sharp / Big money / Whale / Loaded-up tags for one side of a DraftKings split.

    Money % above ticket % only says the bets on that side are bigger. It counts as
    Sharp only when the book also moved the spread that way; otherwise it is Big money,
    or Whale when a few very large bets sit on a side the book isn't moving for.
    """
    handle, bets = split.get('handle_pct'), split.get('bets_pct')
    if handle is None or bets is None:
        return []
    tags = []
    gap = handle - bets
    # Books move the number for pros and leave it alone for high-rollers, so the line
    # decides which one it is: moved their way = Sharp, big lopsided money it ignores = Whale.
    if gap >= SHARP_GAP and line_move is not None and line_move >= LINE_CONFIRM:
        tags.append(('sharp', '🦈 Sharp', f'money {round(gap)} pts above tickets{line_note(line_move)}'))
    elif gap >= WHALE_GAP and bets <= WHALE_MAX_BETS:
        tags.append(('whale', '🐋 Whale', f'{round(handle)}% of the money on {round(bets)}% of the bets{line_note(line_move)}'))
    elif gap >= SHARP_GAP:
        tags.append(('big', '💰 Big money', f'money {round(gap)} pts above tickets{line_note(line_move)}'))
    prior = split.get('prior')
    if prior and prior.get('handle_pct') is not None and prior.get('bets_pct') is not None:
        jump = handle - prior['handle_pct']
        if jump >= LOADED_JUMP and bets - prior['bets_pct'] <= jump / 2:
            tags.append(('loaded', '🚨 Loaded up', f'money {round(prior["handle_pct"])}% → {round(handle)}% since last refresh'))
    return tags


def split_block(g, splits):
    if not splits:
        return ''
    by_team = {s['team_key']: s for s in splits}
    home = by_team.get(normal(g['home_name']))
    away = by_team.get(normal(g['away_name']))
    if not home or not away:
        return ''
    hc, ac = split_colors(g)
    home_move = home.get('home_line_move')

    def row(label, key):
        h = round(home[key])
        a = round(away[key])
        return (f'<div class="split-row"><b>{h}%</b><div class="split-bar">'
                f'<i style="width:{h}%;background:{hc}"></i><i style="width:{a}%;background:{ac}"></i></div>'
                f'<b class="r">{a}%</b><span>{label}</span></div>')

    tags = ''.join(
        f'<div class="money-tag"><em class="mt-{kind}">{label}</em> <b>{esc(g[name])}</b> · {detail}</div>'
        for split, name, sign in ((home, 'home_name', 1), (away, 'away_name', -1))
        for kind, label, detail in money_tags(split, None if home_move is None else sign * home_move))

    return (f'<div class="split"><div class="split-label">DraftKings splits · {esc(g["home_name"])} vs {esc(g["away_name"])}</div>'
            f'{row("Handle", "handle_pct")}{row("Bets", "bets_pct")}{tags}</div>')


KALSHI_MIN_DOLLARS = 1000   # below this the market is too thin to say anything
KALSHI_BIG_BET = 10000      # a single trade this size gets the whale
KALSHI_LEAN = 15            # dollar share this many pts off the win price = money leaning that way


def dollars(x):
    return f'${x / 1e6:.1f}M' if x >= 1e6 else f'${x / 1e3:.0f}k' if x >= 1e4 else f'${x / 1e3:.1f}k' if x >= 1e3 else f'${x:.0f}'


def kalshi_block(g, k):
    """Real dollars traded on each side of Kalshi's winner market (straight-up, not the spread)."""
    if not k:
        return ''
    home_d, away_d = k.get('home_dollars') or 0, k.get('away_dollars') or 0
    total = home_d + away_d
    if total < KALSHI_MIN_DOLLARS:
        return ''
    hc, ac = split_colors(g)
    h = round(100 * home_d / total)
    detail = f'💵 <b>{dollars(total)}</b> bet'
    day = (k.get('home_dollars_24h') or 0) + (k.get('away_dollars_24h') or 0)
    if day >= KALSHI_MIN_DOLLARS:
        day_side = 'home_name' if (k.get('home_dollars_24h') or 0) >= day / 2 else 'away_name'
        day_pct = round(100 * max(k.get('home_dollars_24h') or 0, k.get('away_dollars_24h') or 0) / day)
        detail += f' · last 24h {dollars(day)}, {day_pct}% on <b>{esc(g[day_side])}</b>'
    # Favorites cost more per contract, so dollars pile on them by default. The read is
    # dollars vs. the price: more of the money on a side than its win chance implies.
    lean = ''
    hp, ap = k.get('home_price') or 0, k.get('away_price') or 0
    if hp + ap > 0:
        implied = 100 * hp / (hp + ap)
        fav = 'home_name' if implied >= 50 else 'away_name'
        detail += f' · priced <b>{esc(g[fav])}</b> {round(max(implied, 100 - implied))}% to win'
        edge = h - implied
        # Only on competitive games: lopsided ones draw lottery-ticket money on the long shot.
        if abs(edge) >= KALSHI_LEAN and 25 <= implied <= 75:
            side = 'home_name' if edge > 0 else 'away_name'
            lean = (f'<div class="money-tag"><em class="mt-sharp">🔥 Money lean</em> <b>{esc(g[side])}</b> · '
                    f'{round(abs(edge))} pts more of the dollars than the odds imply</div>')
    big = ''
    if k.get('biggest_side') and (k.get('biggest_dollars') or 0) >= KALSHI_MIN_DOLLARS:
        icon = '🐋 ' if k['biggest_dollars'] >= KALSHI_BIG_BET else ''
        big = (f'<div class="money-tag">{icon}Biggest single bet <b>{dollars(k["biggest_dollars"])}</b>'
               f' on <b>{esc(g[k["biggest_side"] + "_name"])}</b></div>')
    return (f'<div class="split"><div class="split-label">Kalshi real money · to win the game</div>'
            f'<div class="split-row"><b>{h}%</b><div class="split-bar">'
            f'<i style="width:{h}%;background:{hc}"></i><i style="width:{100 - h}%;background:{ac}"></i></div>'
            f'<b class="r">{100 - h}%</b><span>Dollars</span></div>'
            f'<div class="money-tag">{detail}</div>{lean}{big}</div>')


def _rgb(hex6):
    hex6 = (hex6 or '').strip().lstrip('#')
    if not re.fullmatch(r'[0-9a-fA-F]{6}', hex6):
        return None
    return tuple(int(hex6[i:i + 2], 16) for i in (0, 2, 4))


def _luma(rgb):
    return 0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2]


def _visible(rgb):
    # Dark primaries (navy, maroon) vanish against the panel; lift them toward white but keep the hue.
    if rgb is None:
        return None
    while _luma(rgb) < 55:
        rgb = tuple(round(v + (255 - v) * 0.18) for v in rgb)
    return rgb


def _distance(a, b):
    return sum((x - y) ** 2 for x, y in zip(a, b)) ** 0.5


def _saturated(rgb):
    return max(rgb) - min(rgb) >= 50


def split_colors(g):
    fallbacks = [(47, 142, 255), (255, 92, 102), (53, 212, 136)]
    home_opts = [c for c in map(_visible, (_rgb(g['home_color']), _rgb(g['home_alt']))) if c]
    away_opts = [c for c in map(_visible, (_rgb(g['away_color']), _rgb(g['away_alt']))) if c]
    pairs = [(h, a, hi + ai) for hi, h in enumerate(home_opts + fallbacks) for ai, a in enumerate(away_opts + fallbacks)
             if _distance(h, a) >= 90]
    # Saturated beats white/grey alternates, team colors beat fallbacks, then the widest separation.
    best = max(pairs, key=lambda p: (_saturated(p[0]) + _saturated(p[1]),
                                     -(p[0] in fallbacks) - (p[1] in fallbacks), -p[2], _distance(p[0], p[1])))
    return _css(best[0]), _css(best[1])


def _css(rgb):
    return '#%02x%02x%02x' % rgb


def projection_block(g, proj):
    if not proj or proj.get('lean_home_spread') is None:
        return ''
    line_val = proj['lean_home_spread']
    label = 'Pick’em' if line_val == 0 else esc(g['home_name'] if line_val < 0 else g['away_name']) + ' ' + spread_text(-abs(line_val))
    diff = None if g['home_spread'] is None else g['home_spread'] - line_val
    diff_label = ('Unavailable — no market spread' if diff is None
                  else f"{half(abs(diff))} pts" + (' · same as market' if diff == 0 else ' toward ' + esc(g['home_name'] if diff > 0 else g['away_name'])))
    score_line = ''
    if proj.get('home_points') is not None and proj.get('away_points') is not None:
        score_line = f'<div class="projected-score">Projected score: {esc(g["home_name"])} {half(proj["home_points"])} · {esc(g["away_name"])} {half(proj["away_points"])}</div>'
    return (f'<div class="projection"><div><b>Our projected line: {label}</b></div>'
            f'<div>Difference vs market: {diff_label}</div>{score_line}</div>')


def matchup_card(g, home_notes, away_notes, home_rating, away_rating, w, proj, splits, season_games, kalshi=None,
                 yardage=None, efficiency=None, roster=None):
    yardage = yardage or {}
    efficiency = efficiency or {}
    roster = roster or {}
    home_side = (f'<div class="home">{team_title(g, "home")}{grades_block(home_rating, season_games.get(g["home_id"], 0))}'
                 f'{yardage.get("home", "")}{efficiency.get("home", "")}{roster.get("home", "")}'
                 f'<div class="stadium">{esc(g["venue_name"] or "Venue unavailable")}</div>{weather_text(w, g["indoor"])}'
                 f'{notes_block(home_notes)}</div>')
    away_side = (f'<div class="away">{team_title(g, "away")}{grades_block(away_rating, season_games.get(g["away_id"], 0))}'
                 f'{yardage.get("away", "")}{efficiency.get("away", "")}{roster.get("away", "")}{notes_block(away_notes)}</div>')
    status = f' · {esc(g["status"])}' if g['status'] and g['status'] != 'Scheduled' else ''
    market_source = esc(g['odds_status'] if g['home_spread'] is None else g['market_source'])
    market = (f'<div class="market"><div class="kickoff"><b>{esc(time_label(g["kickoff"]))}</b>{status}</div>'
              f'<div class="total">O/U {half(g["total"])}</div>{lean_line(g, proj)}{projection_block(g, proj)}'
              f'{model_detail(g, proj)}{split_block(g, splits)}{kalshi_block(g, kalshi)}<div class="market-source">{market_source}</div></div>')
    return f'<article class="match" id="g{esc(g["game_id"])}">{weather_alert_block(w)}{home_side}{market}{away_side}</article>'


def sharp_card(rows, rec, page_game_ids):
    """The straight-bet list: sides where DraftKings' money share beats its ticket
    share by SHARP_GAP+. Logged at first sighting, graded as games finish."""
    def pick_name(r):
        return r['hn'] if r['side'] == 'home' else r['an']

    def opp_name(r):
        return r['an'] if r['side'] == 'home' else r['hn']

    def spread(v):
        return '—' if v is None else ('PK' if v == 0 else f'{v:+g}')

    body = []
    for r in sorted(rows, key=lambda x: (x['completed'], -(x['gap'] or 0))):
        strong = (r['gap'] or 0) >= 20
        res = ''
        if r['su_result']:
            res = (f'<span class="{"win" if r["su_result"] == "win" else "loss"}">{r["su_result"].upper()} SU</span> · '
                   f'<span class="{"win" if r["ats_result"] == "win" else ("loss" if r["ats_result"] == "loss" else "")}">{(r["ats_result"] or "—").upper()} ATS</span>'
                   f' <small>({r["home_score"]}–{r["away_score"]})</small>')
        elif r['completed']:
            res = 'grading…'
        else:
            res = esc(time_label(r['kickoff']))
        move = r['line_move']
        move_txt = '—' if move is None else (f'<b class="win">{move:+g} toward</b>' if move >= sharp_side.MOVE_FLAG else
                                             (f'<span class="loss">{move:+g} against</span>' if move <= -sharp_side.MOVE_FLAG else f'{move:+g}'))
        link = f'<a href="#g{esc(r["game_id"])}">' if r['game_id'] in page_game_ids else '<span>'
        close_link = '</a>' if r['game_id'] in page_game_ids else '</span>'
        now_line = spread(r['home_spread'] if r['side'] == 'home' else (None if r['home_spread'] is None else -r['home_spread']))
        body.append(
            f'<tr class="{"strong" if strong else ""}{" done" if r["su_result"] else ""}">'
            f'<td>{link}<b>{esc(pick_name(r))}</b>{close_link}<br><small>{"vs" if r["side"] == "home" else "at"} {esc(opp_name(r))}</small></td>'
            f'<td>{r["gap"]:+.0f}<br><small>{r["last_handle_pct"]:.0f}% money / {r["last_bets_pct"]:.0f}% tickets</small></td>'
            f'<td>{spread(r["spread_at_pick"])}<br><small>now {now_line}</small></td>'
            f'<td>{move_txt}</td>'
            f'<td>{"yes" if r["model_agrees"] else "no"}</td>'
            f'<td>{res}</td></tr>')
    rec_line = ''
    if rec and rec['graded']:
        rec_line = (f'<p class="sharp-rec">Season record of this list: <b>{rec["su"]} straight up ({rec["su_pct"]}%)</b> · '
                    f'<b>{rec["ats"]} ATS</b> at the close · {rec["ats_at_pick"]} ATS at the line when first listed · {rec["graded"]} graded.</p>')
    intro = ('<p class="muted" style="line-height:1.7">Sides where DraftKings’ <b>share of money beats its share of tickets by '
             f'{sharp_side.SHARP_GAP:g}+ points</b>: a few big bets against many small ones. On 82 games this season before this list '
             'existed, that side won <b>60% straight up</b> on lines near pick’em and covered 58%. Our own model lean went 47%. '
             'Gaps of 20+ are highlighted. Each game is logged the first run it qualifies, with the line at that moment, and never removed, '
             'so the record above is what you could have bet. Small sample so far; give it eight weeks before trusting it.</p>')
    table = ('<div class="scroll"><table class="sharp"><thead><tr><th>Side</th><th>Money − tickets</th><th>Line when listed</th>'
             '<th>Line move toward pick</th><th>Model agrees</th><th>Result / kickoff</th></tr></thead>'
             f'<tbody>{"".join(body)}</tbody></table></div>') if body else '<div class="empty">No side has a 10-point money gap yet this week.</div>'
    return f'<div class="card"><h2>Sharp Side — straight bets</h2>{rec_line}{intro}{table}</div>'


def method_note(games, proj_by_game):
    """Standing note in place of the old ranked pick list."""
    scored = [proj_by_game[g['game_id']] for g in games
              if (proj_by_game.get(g['game_id']) or {}).get('lean_edge_points') is not None]
    far = sum(1 for p in scored if abs(p['lean_edge_points']) >= 6)
    tally = (f'{len(scored)} matchups projected · {far} sit 6+ pts off the market'
             if scored else 'No projections for this week yet')
    return ('<div class="card"><h2>How to read this page</h2>'
            f'<p class="muted" style="line-height:1.7">{esc(tally)}. '
            'Games are listed in kickoff order and are <b>not</b> ranked as picks. '
            'Measured walk-forward over the 2025–26 seasons, this model does not beat the '
            "closing line (margin MAE 13.1 against the market's 11.8), and its error grows "
            'the further it strays from that line. Confidence below rates how much to trust '
            'the projection, so it <b>falls</b> as the gap to the market widens — a big '
            'disagreement is a warning, not a signal.</p></div>')


# tier -> (low score, high score, gap-to-market at the HIGH score, gap at the LOW score).
# Note the last two run large-to-small: within every tier the score now falls as the
# model moves away from the closing line, because that is the direction the measured
# error runs (10.7 margin MAE inside a point of the close, 17.9 at 10+ points away).
CONFIDENCE_BANDS = {'High': (7, 10, 3.0, 0.0), 'Moderate': (4, 6, 6.0, 3.0), 'Low': (1, 3, 12.0, 6.0)}


def confidence_rating(proj):
    """1-10 read on how much to trust this projection -- not how good the bet is.

    Inverted 2026-09-20. The old version scored a bigger disagreement with the
    market as more confidence, which had the sign backwards: distance from the
    close measures model error, not edge.
    """
    edge = proj['lean_edge_points'] if proj else None
    if edge is None:
        return None
    # Edge is signed (negative = away lean); the tier label already folds in sample size.
    lo, hi, e_lo, e_hi = CONFIDENCE_BANDS.get(proj.get('confidence'), CONFIDENCE_BANDS['Low'])
    frac = (abs(edge) - e_lo) / (e_hi - e_lo) if e_hi != e_lo else 0.0
    return max(lo, min(hi, int(lo + (hi - lo) * frac + 0.5)))


def render_week(season: int, week: int) -> Path:
    with connect() as con:
        games = con.execute(
            """SELECT g.*, th.name AS home_name, th.logo AS home_logo, th.color AS home_color, th.alt_color AS home_alt,
                      ta.name AS away_name, ta.logo AS away_logo, ta.color AS away_color, ta.alt_color AS away_alt
               FROM games g JOIN teams th ON th.team_id=g.home_id JOIN teams ta ON ta.team_id=g.away_id
               WHERE g.season=? AND g.week=? ORDER BY g.kickoff""", (season, week)).fetchall()
        games = [dict(g) for g in games]
        combined = {r['team_id']: r['rank'] for r in con.execute(
            'SELECT team_id, rank FROM polls WHERE season=? AND poll_type=?', (season, 'combined')).fetchall()}
        for g in games:
            venue = json.loads(g['venue_json'] or '{}')
            g['home_combined'] = combined.get(g['home_id'])
            g['away_combined'] = combined.get(g['away_id'])
            g['indoor'] = venue.get('indoor', False)
            g['venue_name'] = venue.get('fullName')
        games = [g for g in games if g['home_combined'] or g['away_combined']]

        # Latest ratings snapshot: every FBS-rated team gets a grade row; only the combined Top 50 carry a power rank.
        as_of = con.execute('SELECT MAX(as_of_date) AS d FROM team_ratings WHERE season=?', (season,)).fetchone()['d']
        rating_rows = [dict(r) for r in con.execute(
            'SELECT * FROM team_ratings WHERE season=? AND as_of_date=?', (season, as_of)).fetchall()] if as_of else []
        ratings_by_team = {r['team_id']: r for r in rating_rows}
        power_rows = sorted((r for r in rating_rows if r['power_rank'] is not None), key=lambda r: r['power_rank'])
        team_names = {r['team_id']: r['name'] for r in con.execute('SELECT team_id, name FROM teams')}

        notes_by_game = {}
        for r in con.execute('SELECT * FROM game_notes ORDER BY note_order'):
            notes_by_game.setdefault((r['game_id'], r['side']), []).append(r['note_text'])
        weather_by_game = {r['game_id']: dict(r) for r in con.execute('SELECT * FROM weather')}
        proj_by_game = {r['game_id']: dict(r) for r in con.execute('SELECT * FROM projections')}
        splits_by_game = {}
        kalshi_by_game = {r['game_id']: dict(r) for r in con.execute('SELECT * FROM kalshi')}
        # Points the spread has moved toward the home team since the first capture.
        line_span = {}
        for r in con.execute('SELECT game_id, home_spread FROM line_history WHERE home_spread IS NOT NULL ORDER BY captured_at'):
            line_span.setdefault(r['game_id'], [r['home_spread']]).append(r['home_spread'])
        home_line_move = {gid: span[0] - span[-1] for gid, span in line_span.items()}
        prior_split = {}
        for r in con.execute('SELECT * FROM splits_history ORDER BY captured_at'):
            prior_split.setdefault((r['team_key'], r['month_day']), []).append(dict(r))
        for r in con.execute('SELECT * FROM splits WHERE game_id IS NOT NULL'):
            s = dict(r)
            history = prior_split.get((s['team_key'], s['month_day']), [])
            s['prior'] = history[-2] if len(history) > 1 else None
            s['home_line_move'] = home_line_move.get(s['game_id'])
            splits_by_game.setdefault(r['game_id'], []).append(s)
        season_games = {}
        for r in con.execute('SELECT home_id, away_id FROM games WHERE season=? AND completed=1', (season,)):
            for tid in (r['home_id'], r['away_id']):
                season_games[tid] = season_games.get(tid, 0) + 1
        box_logs = season_box(con, season)
        play_logs = season_plays(con, season)
        injuries = injuries_by_team(con)
        portal = transfers_ingest.summary(con, season)
        sharp_rows = sharp_side.this_week(con, season, week)
        sharp_rec = sharp_side.record(con, season)
        fbs_ids = {r['team_id'] for r in con.execute('SELECT team_id FROM teams WHERE fbs=1')}

    summaries = {t: yardage_summary(log) for t, log in box_logs.items()}
    yard_ranks, yard_population = yardage_ranks(summaries, fbs_ids)
    eff_summaries = {t: efficiency_summary(log) for t, log in play_logs.items()}
    eff_ranks, eff_population = efficiency_ranks(eff_summaries, fbs_ids)
    qb_hits = injury_prior.load(season)
    hand = manual.load(names=team_names)
    all_fbs_rows = sorted((r for r in rating_rows if r['team_id'] in fbs_ids and r['rating'] is not None),
                          key=lambda r: -(r['rating'] + hand['by_team'].get(r['team_id'], {}).get('points', 0.0)))

    def card(g):
        notes = {}
        yardage = {}
        efficiency = {}
        roster = {}
        for side in ('home', 'away'):
            tid = g[f'{side}_id']
            notes[side] = list(notes_by_game.get((g['game_id'], side), []))
            qb = qb_change_note(box_logs.get(tid), g['game_date'], team_names)
            if qb:
                notes[side].insert(0, qb)
            yardage[side] = yardage_block(summaries.get(tid), yard_ranks.get(tid, {}), yard_population)
            efficiency[side] = efficiency_block(eff_summaries.get(tid), eff_ranks.get(tid, {}), eff_population)
            roster[side] = roster_block(injuries.get(tid), portal.get(tid), qb_hits.get(tid))
        return matchup_card(g, notes['home'], notes['away'],
                            ratings_by_team.get(g['home_id']), ratings_by_team.get(g['away_id']),
                            weather_by_game.get(g['game_id']), proj_by_game.get(g['game_id']),
                            splits_by_game.get(g['game_id']), season_games,
                            kalshi_by_game.get(g['game_id']), yardage, efficiency, roster)

    cards = ''.join(card(g) for g in games) or '<div class="empty">No Top 50 matchups this week.</div>'

    now = datetime.now().astimezone()
    stamp = now.strftime('%b %d, %I:%M %p').replace(' 0', ' ')
    page = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>NCAAF Handicap — Week {week}</title>
<style>{CSS}</style>
</head>
<body>
<header>
  <div><h1>NCAAF Handicap</h1><p class="tag">SEASON {season} · WEEK {week}</p></div>
  <div id="source" class="muted">Updated {esc(stamp)} · {len(games)} Top-50 matchups · times in {esc(now.tzname())}</div>
</header>
{sharp_card(sharp_rows, sharp_rec, {g['game_id'] for g in games})}
{method_note(games, proj_by_game)}
<div class="card"><h2>This Week</h2><div class="match-list">{cards}</div></div>
<div class="card"><h2>Power Ranking</h2>{_render_power_table(power_rows, team_names, hand, qb_hits)}</div>
<div class="card"><h2>Every FBS Team by Model Rating</h2>{_render_hand_note(hand)}{_render_all_fbs_table(all_fbs_rows, team_names, hand, season_games, qb_hits, eff_summaries, eff_ranks, portal)}</div>
<footer class="muted" style="font-size:11px;margin-top:24px;line-height:1.7">
  Confidence rates trust in the projection, not the quality of a bet, and is not a calibrated cover
  probability. This model has not beaten the closing line in walk-forward testing. See README.md.
</footer>
</body>
</html>
"""
    OUT_PATH.write_text(page, encoding='utf-8')
    return OUT_PATH


def _nudge_cell(hand, team_id):
    a = (hand or {}).get('by_team', {}).get(team_id)
    if not a or not a['points']:
        return '<td class="muted">—</td>'
    cls = 'win' if a['points'] > 0 else 'loss'
    note = f' title="{esc(a["note"])}"' if a.get('note') else ''
    return f'<td class="{cls}"{note}>{a["points"]:+.1f}</td>'


def _render_hand_note(hand):
    n = len((hand or {}).get('by_team', {}))
    bad = (hand or {}).get('unmatched', [])
    text = (f'{n} team(s) carry your adjustment from manual_adjustments.csv.' if n else
            'No manual adjustments in play. Edit manual_adjustments.csv in the project folder (team, points, note) '
            'to nudge a team up or down; the next hourly run applies it.')
    if bad:
        text += ' Not matched to an FBS team: ' + ', '.join(esc(b) for b in bad) + '.'
    return (f'<p class="muted" style="line-height:1.7">{text} Rating is points better than an average FBS team on a '
            'neutral field. The nudge is added to every game that team plays and the record is graded with and '
            'without it, so the backtest report can tell whether your hand is helping.</p>')


def _qb_cell(qb_hits, team_id):
    hit = (qb_hits or {}).get(team_id)
    if not hit:
        return '<td class="muted">—</td>'
    cls = 'loss' if hit['severity'] == 'out' else ''
    return f'<td class="{cls}" title="{esc(hit["note"])}">{esc(hit["status"])}: {esc(hit["player"])}</td>'


def _render_power_table(rows, team_names, hand=None, qb_hits=None):
    if not rows:
        return '<div class="empty">No power ratings yet this season.</div>'
    body = []
    for t in rows:
        body.append(
            f"<tr><td>{t['power_rank']}</td><td>{esc(team_names.get(t['team_id'], t['team_id']))}</td>"
            f"<td class=\"{trend_class(t['trend'])}\">{trend_text(t['trend'])}</td>"
            f"<td>{half(t['rating'])}</td>{_nudge_cell(hand, t['team_id'])}{_qb_cell(qb_hits, t['team_id'])}"
            f"<td>{('#'+str(t['offense_rank'])) if t['offense_rank'] else '—'}{(' ('+t['offense_grade']+')') if t['offense_grade'] else ''}</td>"
            f"<td>{('#'+str(t['defense_rank'])) if t['defense_rank'] else '—'}{(' ('+t['defense_grade']+')') if t['defense_grade'] else ''}</td>"
            f"<td>{t['games']}</td>"
            f"<td>{('#'+str(t['ap_rank'])) if t['ap_rank'] else '—'}</td>"
            f"<td>#{t['combined_rank']}</td></tr>")
    return ('<div class="scroll"><table><thead><tr><th>#</th><th>Team</th><th>Trend</th><th>Rating</th><th>Your nudge</th>'
            '<th>Starting QB</th><th>Offense</th><th>Defense</th><th>Games</th><th>AP</th><th>Combined</th></tr></thead>'
            f'<tbody>{"".join(body)}</tbody></table></div>')


def _render_all_fbs_table(rows, team_names, hand, season_games, qb_hits=None, eff=None, eff_ranks=None, portal=None):
    """Every rated FBS team, sorted by model rating plus your nudge, so a hand
    adjustment can be judged against the whole list and not just the Top 50."""
    if not rows:
        return '<div class="empty">No ratings yet this season.</div>'
    by = (hand or {}).get('by_team', {})
    eff = eff or {}
    eff_ranks = eff_ranks or {}
    portal = portal or {}
    body = []
    for i, t in enumerate(rows, 1):
        tid = t['team_id']
        nudge = by.get(tid, {}).get('points', 0.0)
        adjusted = t['rating'] + nudge
        e = eff.get(tid) or {}
        rk = eff_ranks.get(tid, {})
        sr = f"{100 * e['sr']:.0f}% <i class=\"muted\">#{rk.get('sr', '—')}</i>" if e.get('sr') is not None else '—'
        sra = f"{100 * e['sr_allowed']:.0f}% <i class=\"muted\">#{rk.get('sr_allowed', '—')}</i>" if e.get('sr_allowed') is not None else '—'
        p = portal.get(tid)
        if p:
            net_cls = 'win' if p['net_rating'] > 0.5 else ('loss' if p['net_rating'] < -0.5 else '')
            port = f"<span class=\"{net_cls}\">{p['net_rating']:+.1f}</span> <i class=\"muted\">({p['in_n']} in / {p['out_n']} out)</i>"
        else:
            port = '—'
        body.append(
            f"<tr><td>{i}</td><td>{esc(team_names.get(tid, tid))}</td>"
            f"<td>{half(t['rating'])}</td>{_nudge_cell(hand, tid)}"
            f"<td><b>{half(adjusted)}</b></td>{_qb_cell(qb_hits, tid)}"
            f"<td>{('#'+str(t['offense_rank'])) if t['offense_rank'] else '—'}{(' ('+t['offense_grade']+')') if t['offense_grade'] else ''}</td>"
            f"<td>{('#'+str(t['defense_rank'])) if t['defense_rank'] else '—'}{(' ('+t['defense_grade']+')') if t['defense_grade'] else ''}</td>"
            f"<td>{sr}</td><td>{sra}</td><td>{port}</td>"
            f"<td>{season_games.get(tid, 0)}</td>"
            f"<td>{('#'+str(t['ap_rank'])) if t['ap_rank'] else '—'}</td></tr>")
    return ('<details><summary>Show all ' + str(len(rows)) + ' teams</summary><div class="scroll"><table><thead><tr>'
            '<th>#</th><th>Team</th><th>Model rating</th><th>Your nudge</th><th>Adjusted</th><th>Starting QB</th>'
            '<th>Offense</th><th>Defense</th><th>Success rate</th><th>Allowed</th><th>Portal net</th>'
            '<th>Games this season</th><th>AP</th></tr></thead>'
            f'<tbody>{"".join(body)}</tbody></table></div></details>')


if __name__ == '__main__':
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument('season', type=int)
    p.add_argument('week', type=int)
    a = p.parse_args()
    print(render_week(a.season, a.week))
