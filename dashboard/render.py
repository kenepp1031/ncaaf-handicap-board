"""Static dashboard.html generator. Pure Python f-strings + one inline CSS
constant, no template engine, no client-side fetch/polling — everything is
read from SQLite once and baked into the page, following NFL 2.0's
dashboard/render.py technique. Visual language (dark-navy theme, matchup
cards, power ranking table) is ported from this app's own app.css/app.js.
"""
from __future__ import annotations

import html
import json
import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common import logo_url
from db.db import connect

OUT_PATH = Path(__file__).resolve().parent / "dashboard.html"

CSS = """
:root{--bg:#060a12;--panel:#0f1826;--panel-alt:#0b1420;--border:#1e2c42;--ink:#e7edf7;--muted:#7c8dab;
--muted2:#5c6c86;--accent:#2f8eff;--win:#35d488;--loss:#ff5c66;--note-bg:#2c2110;--note-fg:#f2b84b;
--weather-bg:#101f33;--weather-fg:#9fd0ff;--tag:#4fa8ff;--total:#bcd6ff;--header-row:#101b2c;--row-border:#1a2536}
*{box-sizing:border-box}html{background:var(--bg)}
body{max-width:1440px;margin:auto;padding:28px;font-family:"Segoe UI",Arial,sans-serif;color:var(--ink);background:var(--bg)}
h1{margin:0;font-size:32px}h2{font-size:21px;margin:0 0 14px}p{color:var(--muted)}
header{display:flex;justify-content:space-between;align-items:center;margin-bottom:18px;gap:14px;flex-wrap:wrap}
.tag{font-size:12px;color:var(--tag);font-weight:700;letter-spacing:1.5px}
.card{background:var(--panel);border:1px solid var(--border);border-radius:12px;padding:20px;margin:16px 0}
small,.muted{color:var(--muted)}#source{font-size:13px;line-height:1.6}
table{width:100%;border-collapse:collapse;font-size:14px}
th{text-align:left;font-size:12px;color:var(--muted);background:var(--header-row);padding:12px 8px}
td{padding:12px 8px;border-bottom:1px solid var(--row-border)}
.scroll{overflow:auto;max-height:520px}
.win{color:var(--win)}.loss{color:var(--loss)}.empty{text-align:center;padding:30px;color:var(--muted2)}
a{color:var(--tag)}
.pill{background:var(--weather-bg);color:var(--weather-fg);border-radius:5px;padding:4px 7px;white-space:nowrap}
.match-head,.match{display:grid;grid-template-columns:minmax(0,1fr) 260px minmax(0,1fr);gap:22px}
.match-head{padding:12px 20px;background:var(--header-row);font-size:12px;font-weight:700;color:var(--muted);text-transform:uppercase;letter-spacing:1px}
.match-head span:nth-child(2){text-align:center}.match-head span:last-child{text-align:right}
.match{padding:24px 20px;border-bottom:1px solid var(--row-border);align-items:center}
.match:nth-child(even){background:var(--panel-alt)}
.team-title{display:flex;align-items:center;gap:12px}.team-title img{width:46px;height:46px;object-fit:contain}
.team-title h3{font-size:21px;margin:4px 0}.rank{color:var(--tag);font-size:14px}
.team-sub{font-size:12px;color:var(--muted)}
.away{text-align:right}.away .team-title{justify-content:flex-end}
.stadium{font-size:12px;color:var(--muted2);margin:12px 0 6px;line-height:1.7}
.weather{display:inline-block;font-size:12px;background:var(--weather-bg);color:var(--weather-fg);padding:7px 9px;border-radius:5px;line-height:1.6}
.weather small{font-size:10px}
.market{text-align:center}.kickoff{font-size:11px;color:var(--muted);margin-bottom:9px}
.total{font-size:13px;font-weight:700;margin-bottom:9px;color:var(--total)}
.market-source{font-size:10px;color:var(--muted2);margin-top:8px}
.split{font-size:11px;margin-top:8px;color:var(--muted2);line-height:1.6}
.match-list{max-height:900px;overflow:auto}
.roster{display:grid;grid-template-columns:repeat(5,1fr);gap:10px;margin-top:15px}
.roster div{padding:8px;border-bottom:1px solid var(--row-border);font-size:13px}
details summary{cursor:pointer;font-weight:600}
.power{font-size:12px;color:var(--muted);margin-top:10px;line-height:1.6;text-align:left}.power b{color:var(--tag)}
.notes{margin-top:8px;display:flex;gap:4px;flex-wrap:wrap}
.note{display:inline-block;font-size:10px;background:var(--note-bg);color:var(--note-fg);padding:3px 7px;border-radius:4px;margin:2px 0 0}
.away .notes{justify-content:flex-end}
.model-detail{font-size:11px;color:var(--muted);text-align:left;margin:9px 0 2px;border-top:1px dashed var(--border);padding-top:7px;line-height:1.7}
.model-detail summary{font-size:10px;font-weight:700;letter-spacing:.6px;text-transform:uppercase;color:var(--muted2);text-align:center}
.model-detail>div{margin-top:6px}.model-detail b{color:var(--ink)}.model-detail small{display:block;color:var(--muted2);font-size:10px}
.model-weather{background:var(--weather-bg);color:var(--weather-fg);padding:5px 7px;border-radius:4px}
.health{font-size:12px;margin-top:12px}
.health-row{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:10px;padding:7px 0;border-bottom:1px solid var(--row-border);align-items:baseline}
.health-row span{color:var(--muted)}.health-row b{color:var(--ink);text-align:right}
.health-row small{grid-column:1/-1;color:var(--muted2);font-size:10px;line-height:1.6}
.weather-alert{grid-column:1/-1;background:var(--loss);color:#fff;font-weight:700;font-size:13px;padding:9px 14px;border-radius:6px;margin-bottom:14px}
.toppick{position:relative}.toppick .match{border-radius:8px;border:1px solid var(--accent)}
.rating-badge{position:absolute;top:10px;left:10px;z-index:2;background:var(--accent);color:#fff;font-size:12px;font-weight:700;padding:5px 10px;border-radius:20px}
.rating-badge b{font-size:15px}
.previous-game{margin-top:10px;padding-top:6px;border-top:1px dashed var(--border);font-size:11px;line-height:1.6;color:var(--muted)}
.previous-game small{display:block;font-size:9px;font-weight:700;letter-spacing:.5px}
.grades{font-size:13px;line-height:1.7;margin:10px 0}.grades b{color:var(--tag)}.grades small{display:block;color:var(--muted);font-size:10px}
.model-lean{font-size:13px;margin:8px 0;line-height:1.6}
.projection{font-size:11px;color:var(--muted);margin:8px 0 10px;line-height:1.7}.projection b{color:var(--ink)}
.projected-score{font-size:10px;margin-top:4px}
[hidden]{display:none!important}
@media(max-width:850px){body{padding:12px}header{display:block}.match-head,.match{grid-template-columns:minmax(0,1fr) 175px minmax(0,1fr);gap:8px}.match{padding:18px 5px}.team-title{display:block}.away .team-title img{float:right}.team-title h3{font-size:16px}.team-title img{width:34px;height:34px}.roster{grid-template-columns:repeat(2,1fr)}.stadium{font-size:11px}}
@media(max-width:550px){.match-head,.match{grid-template-columns:minmax(0,1fr) 130px minmax(0,1fr)}.team-title h3{font-size:14px}.weather{padding:4px}.match-head{font-size:10px;padding:10px 5px}}
"""


def esc(s) -> str:
    return html.escape(str(s)) if s is not None else ''


def half(n):
    return '—' if n is None else f'{round(float(n) * 2) / 2:.1f}'


def spread_text(n):
    if n is None:
        return '—'
    return ('+' if n > 0 else '') + half(n)


def money(n):
    if n is None:
        return '—'
    return f'${n / 1e6:.1f}M' if n >= 1e6 else f'${round(n / 1e3)}K'


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


def team_title(g, side, notes_by_side):
    tid = g[f'{side}_id']
    name = g[f'{side}_name']
    logo = logo_url(g[f'{side}_logo'])
    rank = g[f'{side}_combined']
    sub = ('DESIGNATED HOME · NEUTRAL SITE' if g['neutral'] else 'HOME') if side == 'home' else 'AWAY'
    img = f'<img src="{esc(logo)}" alt="" loading="lazy">' if logo else ''
    rank_html = f'<span class="rank" title="Combined CBS / AP / Coaches poll">Poll #{rank}</span> ' if rank else ''
    return f'<div class="team-title">{img}<div><div class="team-sub">{esc(sub)}</div><h3>{rank_html}{esc(name)}</h3></div></div>'


def grades_block(rating_row):
    if rating_row is None:
        return '<div class="grades">Outside FBS ranking pool<small>Not assigned an FBS rank or grade</small></div>'
    off = f"#{rating_row['offense_rank']} · {rating_row['offense_grade']}" if rating_row['offense_rank'] else 'Unrated'
    dfn = f"#{rating_row['defense_rank']} · {rating_row['defense_grade']}" if rating_row['defense_rank'] else 'Unrated'
    pop = rating_row['ranking_population'] or '—'
    scope = rating_row['ranking_scope'] or 'FBS'
    games = rating_row['games'] or 0
    provisional = ' · provisional' if games < 4 else ''
    return (f'<div class="grades">Offense <b>{off}</b><br>Defense <b>{dfn}</b>'
            f'<small>Out of {pop} {esc(scope)} teams · {games} games across recent seasons{provisional}</small></div>')


def ats_text(record):
    if not record or record['wins'] + record['losses'] + record['pushes'] == 0:
        return ''
    return f"{record['wins']}-{record['losses']}-{record['pushes']} ATS"


def notes_block(notes, ats):
    items = ([ats] if ats else []) + notes
    if not items:
        return ''
    pills = ''.join(f'<span class="note">{esc(n)}</span>' for n in items)
    return f'<div class="notes">{pills}</div>'


def weather_text(w, indoor):
    if indoor:
        return '<span class="weather">Indoor venue · field conditions sheltered</span>'
    if not w or w['status'] not in ('Kickoff through approximately 3 hours after kickoff',):
        status = (w['status'] if w else 'Game forecast unavailable')
        return f'<span class="weather">{esc(status)}</span>'
    return (f'<span class="weather"><b>{round(w["temp_f"])}°F</b>, wind {round(w["wind_mph"] or 0)} mph'
            f'<br><small>updated {esc(w["checked_at"])}</small></span>')


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
                    f'<small>Needs 1.0 pt for any lean; 2.0 pts and two games each for Moderate; '
                    f'4.0 pts and five games each for High.</small></div>')
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
    pooled = json.loads(proj['pooled_fcs_json']) if proj.get('pooled_fcs_json') else []
    if pooled:
        who = ' and '.join(esc(g[f'{s}_name']) for s in pooled)
        rows.append(f'<div>FCS opponent: <b>{who}</b><small>Rated as a pooled FCS baseline, not individually. '
                    f'One or two games against FBS teams cannot rate a school on its own.</small></div>')
    if proj['confidence_detail']:
        rows.append(f'<div><small>{esc(proj["confidence_detail"])}</small></div>')
    return f'<details class="model-detail"><summary>Model detail</summary>{"".join(rows)}</details>' if rows else ''


def lean_line(proj):
    side = (proj.get('lean_side') or '').lower() if proj else ''
    if side and proj.get(f'{side}_name'):
        text = esc(proj[f'{side}_name']) + ' ' + spread_text(proj.get(f'{side}_spread'))
    else:
        text = 'No lean'
    confidence = esc(proj['confidence']) if proj and proj.get('confidence') else 'Unavailable'
    return f'<div class="model-lean">Our lean: <b>{text}</b><br><small>Confidence: {confidence}</small></div>'


def matchup_card(g, home_notes, away_notes, home_ats, away_ats, home_rating, away_rating, w, proj):
    weather_block = weather_alert_block(w)
    home_side = (f'<div class="home">{team_title(g, "home", None)}{grades_block(home_rating)}'
                 f'<div class="stadium">{esc(g["venue_name"] or "Venue unavailable")}</div>{weather_text(w, g["indoor"])}'
                 f'{notes_block(home_notes, ats_text(home_ats))}</div>')
    away_side = (f'<div class="away">{team_title(g, "away", None)}{grades_block(away_rating)}'
                 f'{notes_block(away_notes, ats_text(away_ats))}</div>')
    status = f' · {esc(g["status"])}' if g['status'] and g['status'] != 'Scheduled' else ''
    kickoff = g['kickoff']
    try:
        kickoff_label = datetime.fromisoformat(kickoff).strftime('%a %-m/%-d %-I:%M %p')
    except Exception:
        kickoff_label = kickoff
    lean = lean_line(dict(proj, home_name=g['home_name'], away_name=g['away_name'],
                           home_spread=g['home_spread'], away_spread=g['away_spread']) if proj else None)
    projection_html = ''
    if proj and proj.get('lean_home_spread') is not None:
        line_val = proj['lean_home_spread']
        label = 'Pick’em' if line_val == 0 else esc(g['home_name'] if line_val < 0 else g['away_name']) + ' ' + spread_text(-abs(line_val))
        diff = None if g['home_spread'] is None else g['home_spread'] - line_val
        diff_label = ('Unavailable — no market spread' if diff is None
                       else f"{half(abs(diff))} pts" + (' · same as market' if diff == 0 else ' toward ' + esc(g['home_name'] if diff > 0 else g['away_name'])))
        score_line = ''
        if proj.get('home_points') is not None and proj.get('away_points') is not None:
            score_line = f'<div class="projected-score">Projected score: {esc(g["home_name"])} {half(proj["home_points"])} · {esc(g["away_name"])} {half(proj["away_points"])}</div>'
        projection_html = (f'<div class="projection"><div><b>Our projected line: {label}</b></div>'
                            f'<div>Difference vs market: {diff_label}</div>{score_line}</div>')
    detail = model_detail(g, proj) if proj else ''
    market_source = esc(g['odds_status'] if g['home_spread'] is None else g['market_source'])
    market = (f'<div class="market"><div class="kickoff">{esc(kickoff_label)}{status}</div>'
              f'<div class="total">O/U {half(g["total"])}</div>{lean}{projection_html}{detail}'
              f'<div class="market-source">{market_source}</div></div>')
    return f'<article class="match">{weather_block}{home_side}{market}{away_side}</article>'


def confidence_rating(proj):
    edge = proj['lean_edge_points'] if proj else None
    if edge is None:
        return None
    return max(1, min(10, round(edge * 2.5)))


def render_week(season: int, week: int) -> Path:
    with connect() as con:
        games = con.execute(
            """SELECT g.*, th.name AS home_name, th.logo AS home_logo, ta.name AS away_name, ta.logo AS away_logo
               FROM games g JOIN teams th ON th.team_id=g.home_id JOIN teams ta ON ta.team_id=g.away_id
               WHERE g.season=? AND g.week=? ORDER BY g.kickoff""", (season, week)).fetchall()
        games = [dict(g) for g in games]
        combined = {r['team_id']: r['rank'] for r in con.execute(
            'SELECT team_id, rank FROM polls WHERE season=? AND poll_type=?', (season, 'combined')).fetchall()}
        for g in games:
            g['home_combined'] = combined.get(g['home_id'])
            g['away_combined'] = combined.get(g['away_id'])
            g['indoor'] = json.loads(g['venue_json'] or '{}').get('indoor', False)
            g['venue_name'] = (json.loads(g['venue_json'] or '{}').get('fullName'))
        games = [g for g in games if g['home_combined'] or g['away_combined']]

        as_of_row = con.execute('SELECT MAX(as_of_date) AS d FROM team_ratings WHERE season=?', (season,)).fetchone()
        as_of = as_of_row['d'] if as_of_row else None
        ratings_by_team = {}
        power_rows = []
        if as_of:
            power_rows = [dict(r) for r in con.execute(
                'SELECT * FROM team_ratings WHERE season=? AND as_of_date=? ORDER BY power_rank', (season, as_of)).fetchall()]
            for r in power_rows:
                ratings_by_team[r['team_id']] = r
        team_names = {r['team_id']: r['name'] for r in con.execute('SELECT team_id, name FROM teams')}

        notes_by_game = {}
        for r in con.execute('SELECT * FROM game_notes ORDER BY note_order'):
            notes_by_game.setdefault((r['game_id'], r['side']), []).append(r['note_text'])

        weather_by_game = {r['game_id']: dict(r) for r in con.execute('SELECT * FROM weather')}
        proj_by_game = {r['game_id']: dict(r) for r in con.execute('SELECT * FROM projections')}

        status_row = con.execute('SELECT MAX(as_of_date) FROM team_ratings').fetchone()

    def team_games_for(tid):
        return [g for g in games if g['home_id'] == tid or g['away_id'] == tid]

    cards = []
    for g in games:
        proj = proj_by_game.get(g['game_id'])
        home_notes = notes_by_game.get((g['game_id'], 'home'), [])
        away_notes = notes_by_game.get((g['game_id'], 'away'), [])
        w = weather_by_game.get(g['game_id'])
        # ATS-record pills (e.g. "6-2-0 ATS") are omitted here: ratings/power.py
        # doesn't currently persist per-game ATS records to a queryable table.
        cards.append((g, home_notes, away_notes, None, None, ratings_by_team.get(g['home_id']),
                      ratings_by_team.get(g['away_id']), w, proj))

    top_picks = sorted(
        [(c[0], c[-1]) for c in cards if c[-1] and not c[0]['completed'] and c[-1].get('lean_side')],
        key=lambda gp: abs(gp[1].get('lean_edge_points') or 0), reverse=True)[:5]

    games_html = ''.join(matchup_card(*c[:9]) for c in cards) or '<div class="empty">No Top 50 matchups this week.</div>'
    top_picks_html = ''
    if top_picks:
        blocks = []
        for g, p in top_picks:
            c = next(c for c in cards if c[0]['game_id'] == g['game_id'])
            rating = confidence_rating(p)
            blocks.append(f'<div class="toppick"><div class="rating-badge">Confidence <b>{rating}</b>/10</div>{matchup_card(*c[:9])}</div>')
        top_picks_html = '<div class="card"><h2>Top Picks This Week</h2>' + ''.join(blocks) + '</div>'

    power_html = _render_power_table(power_rows, team_names)
    now = datetime.now().astimezone().isoformat(timespec='seconds')

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
  <div id="source" class="muted">Generated {esc(now)} · {len(games)} Top-50 matchups</div>
</header>
{top_picks_html}
<div class="card"><h2>This Week</h2><div class="match-list">{games_html}</div></div>
<div class="card"><h2>Power Ranking</h2>{power_html}</div>
<footer class="muted" style="font-size:11px;margin-top:24px;line-height:1.7">
  Confidence is a qualitative label, not a calibrated cover probability. See README.md for the full model methodology.
</footer>
</body>
</html>
"""
    OUT_PATH.write_text(page, encoding='utf-8')
    return OUT_PATH


def _render_power_table(rows, team_names):
    if not rows:
        return '<div class="empty">No power ratings yet this season.</div>'
    body = []
    for t in rows:
        body.append(
            f"<tr><td>{t['power_rank']}</td><td>{esc(team_names.get(t['team_id'], t['team_id']))}</td>"
            f"<td class=\"{trend_class(t['trend'])}\">{trend_text(t['trend'])}</td>"
            f"<td>{half(t['rating'])}</td>"
            f"<td>{('#'+str(t['offense_rank'])) if t['offense_rank'] else '—'}{(' ('+t['offense_grade']+')') if t['offense_grade'] else ''}</td>"
            f"<td>{('#'+str(t['defense_rank'])) if t['defense_rank'] else '—'}{(' ('+t['defense_grade']+')') if t['defense_grade'] else ''}</td>"
            f"<td>{t['games']}</td>"
            f"<td>{('#'+str(t['ap_rank'])) if t['ap_rank'] else '—'}</td>"
            f"<td>#{t['combined_rank']}</td></tr>")
    return ('<div class="scroll"><table><thead><tr><th>#</th><th>Team</th><th>Trend</th><th>Rating</th>'
            '<th>Offense</th><th>Defense</th><th>Games</th><th>AP</th><th>Combined</th></tr></thead>'
            f'<tbody>{"".join(body)}</tbody></table></div>')


if __name__ == '__main__':
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument('season', type=int)
    p.add_argument('week', type=int)
    a = p.parse_args()
    print(render_week(a.season, a.week))
