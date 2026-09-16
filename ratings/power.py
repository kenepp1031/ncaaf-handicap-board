"""Opponent-adjusted scoring model, re-plumbed onto SQLite. Confidence is
qualitative, not a win probability. Math ported unchanged from power.py; only
the storage (DB tables instead of one live.json payload dict) changed.
"""
from __future__ import annotations

import json
import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common import HOSTILE_ENVIRONMENTS, POOLED_FCS, RIVALRIES, normal
from db.db import connect
from ratings.handicap_model import Model
from ratings import nil_prior, officiating_prior, talent_prior

MIN_GAMES = 2
# Chosen by walk-forward test — see README/CHANGELOG. Do not retune casually.
MODEL_RIDGE = 1.5
MODEL_HALF_LIFE = 365.0
BYE_REST_DAYS = 12
WIND_LEAN_MPH = 15
RAIN_LEAN_IN = 0.05
LETDOWN_LEAN_POINTS = 1.5
LOOKAHEAD_LEAN_POINTS = 1.0
BYE_LEAN_POINTS = 1.0
AP_BLEND_WEIGHT = 0.4

GRADE_CUTOFFS = [(0.95, 'A+'), (0.85, 'A'), (0.75, 'A-'), (0.65, 'B+'), (0.55, 'B'), (0.45, 'B-'),
                  (0.35, 'C+'), (0.25, 'C'), (0.15, 'C-'), (0.08, 'D')]

# See ingest/rankings.py's _FBS_ALIASES — same canonicalization, needed again
# here because pooling keys off team *names*, not the poll ingest step.
_FBS_ALIASES = dict(zip(
    'missstate ndakotast iowast sandiegost michiganst wmichigan coloradost washingtonst gasouthern jacksonvillest arkansasst appst fresnost texasst utahst kennesawst fau ccarolina fiu newmexicost somiss emichigan cmichigan georgiast sacramentost missourist middletenn kentst ballst sanjosstate'.split(),
    'mississippistate northdakotastate iowastate sandiegostate michiganstate westernmichigan coloradostate washingtonstate georgiasouthern jacksonvillestate arkansasstate appalachianstate fresnostate texasstate utahstate kennesawstate floridaatlantic coastalcarolina floridainternational newmexicostate southernmiss easternmichigan centralmichigan georgiastate sacramentostate missouristate middletennessee kentstate ballstate sanjosestate'.split()))
_FBS_ALIASES.update(fiu='floridainternational', newmexicost='newmexicostate', somiss='southernmiss')


def fbs_key(name):
    key = normal(name)
    return _FBS_ALIASES.get(key, key)


def pooled(team_id, names, fbs_names):
    if not fbs_names:
        return team_id
    return team_id if fbs_key(names.get(team_id, '')) in fbs_names else POOLED_FCS


def pooled_rows(rows, names, fbs_names):
    if not fbs_names:
        return rows
    return [dict(r, home_team=pooled(r['home_team'], names, fbs_names),
                 away_team=pooled(r['away_team'], names, fbs_names)) for r in rows]


def letter_grade(value, population):
    if value is None:
        return None
    values = [v for v in population if v is not None]
    if not values:
        return None
    percentile = sum(1 for v in values if v < value) / len(values)
    for cutoff, grade in GRADE_CUTOFFS:
        if percentile >= cutoff:
            return grade
    return 'F'


def hostile_environment_note(home_team, neutral):
    if neutral:
        return None
    hit = HOSTILE_ENVIRONMENTS.get(normal(home_team))
    if not hit:
        return None
    rank, venue = hit
    return f'Road game at {venue} — hostile environment #{rank}'


def _row(g):
    return {'date': date.fromisoformat(g['game_date']), 'home_team': g['home_id'], 'away_team': g['away_id'],
            'neutral': bool(g['neutral']), 'home_score': float(g['home_score']), 'away_score': float(g['away_score'])}


def _fetch_completed_rows(con, seasons, as_of):
    placeholders = ','.join('?' for _ in seasons)
    rows = con.execute(
        f"""SELECT * FROM games WHERE season IN ({placeholders}) AND completed=1
            AND home_score IS NOT NULL AND away_score IS NOT NULL AND game_date < ?""",
        (*seasons, as_of.isoformat())).fetchall()
    return [_row(g) for g in rows]


def _fetch_season_games(con, season):
    return [dict(g) for g in con.execute('SELECT * FROM games WHERE season=? ORDER BY kickoff', (season,)).fetchall()]


def _fetch_team_names(con):
    return {r['team_id']: r['name'] for r in con.execute('SELECT team_id, name FROM teams')}


def _fetch_fbs_names(con):
    rows = con.execute('SELECT name FROM teams WHERE fbs=1').fetchall()
    return {fbs_key(r['name']) for r in rows}


def _fetch_ranks(con, season, poll_type):
    return {r['team_id']: r['rank'] for r in con.execute(
        'SELECT team_id, rank FROM polls WHERE season=? AND poll_type=?', (season, poll_type)).fetchall()}


def ats_record(games, team_id, before):
    record = {'wins': 0, 'losses': 0, 'pushes': 0}
    for g in games:
        if not g.get('completed') or g.get('home_score') is None or g.get('home_spread') is None:
            continue
        if date.fromisoformat(g['game_date']) >= before:
            continue
        if g['home_id'] == team_id:
            margin, spread = g['home_score'] - g['away_score'], g['home_spread']
        elif g['away_id'] == team_id:
            margin, spread = g['away_score'] - g['home_score'], -g['home_spread']
        else:
            continue
        covered = margin + spread
        record['pushes' if covered == 0 else ('wins' if covered > 0 else 'losses')] += 1
    return record


def opponent(g, team_id):
    return g['away_id'] if g['home_id'] == team_id else g['home_id']


def _neighbors(games, team_id, game_date):
    played = sorted((g for g in games if team_id in (g['home_id'], g['away_id'])), key=lambda g: g['game_date'])
    before = [g for g in played if g['game_date'] < game_date]
    after = [g for g in played if g['game_date'] > game_date]
    return (before[-1] if before else None), (after[0] if after else None)


def situational_notes(games, team_id, this_week_opp_rank, game_date, combined):
    notes = []
    last_game, next_game = _neighbors(games, team_id, game_date)
    if last_game:
        rest = (date.fromisoformat(game_date) - date.fromisoformat(last_game['game_date'])).days
        if rest >= BYE_REST_DAYS:
            notes.append(f'Off a bye ({rest} days rest)')
        if last_game.get('completed') and last_game.get('home_score') is not None:
            side = 'home' if last_game['home_id'] == team_id else 'away'
            other = 'away' if side == 'home' else 'home'
            won = last_game[side + '_score'] > last_game[other + '_score']
            raw_spread = last_game.get('home_spread')
            team_spread = raw_spread if side == 'home' else (None if raw_spread is None else -raw_spread)
            was_dog = team_spread is not None and team_spread > 0
            if won and was_dog and (this_week_opp_rank is None or this_week_opp_rank > 50):
                notes.append('Letdown risk: won last week as an underdog, now favored on an unranked opponent')
    if next_game:
        next_rank = combined.get(opponent(next_game, team_id))
        if next_rank and next_rank <= 25 and (this_week_opp_rank is None or this_week_opp_rank > 50):
            notes.append(f'Lookahead risk: plays a Top 25 team (#{next_rank}) next week')
    return notes


def weather_note(w):
    if not w or w.get('wind_mph') is None:
        return None
    if w['wind_mph'] >= WIND_LEAN_MPH or (w.get('precip_in') or 0) >= RAIN_LEAN_IN:
        return f"Wind {round(w['wind_mph'])} mph / rain {w.get('precip_in') or 0:g} in — guides lean Under in these spots"
    return None


def weather_alert(w, indoor):
    if not w or indoor:
        return None
    reasons = []
    codes = json.loads(w['weather_codes_json']) if w.get('weather_codes_json') else [w.get('weather_code')]
    if any(c in (56, 57, 66, 67, 68, 69, 79) for c in codes):
        reasons.append('freezing / mixed precipitation (sleet risk)')
    if (w.get('snowfall_in') or 0) > 0 or any(c in (71, 73, 75, 77, 85, 86) for c in codes):
        reasons.append('snow')
    if (w.get('rain_in') or 0) > 0 or (w.get('precip_in') or 0) > 0 or any(c in (51, 53, 55, 61, 63, 65, 80, 81, 82, 95, 96, 99) for c in codes):
        reasons.append('rain / precipitation')
    if (w.get('wind_mph') or 0) >= 15:
        reasons.append(f"wind {round(w['wind_mph'])} mph")
    if (w.get('wind_gusts_mph') or 0) >= 15:
        reasons.append(f"gusts {round(w['wind_gusts_mph'])} mph")
    return 'Game forecast: ' + ', '.join(reasons) if reasons else None


def _has(notes, prefix):
    return any(n.startswith(prefix) for n in notes)


def power_lean(fair_home_spread, home_notes, away_notes):
    lean = fair_home_spread
    if _has(home_notes, 'Letdown risk'):
        lean += LETDOWN_LEAN_POINTS
    if _has(away_notes, 'Letdown risk'):
        lean -= LETDOWN_LEAN_POINTS
    if _has(home_notes, 'Lookahead risk'):
        lean += LOOKAHEAD_LEAN_POINTS
    if _has(away_notes, 'Lookahead risk'):
        lean -= LOOKAHEAD_LEAN_POINTS
    home_bye, away_bye = _has(home_notes, 'Off a bye'), _has(away_notes, 'Off a bye')
    if home_bye and not away_bye:
        lean -= BYE_LEAN_POINTS
    elif away_bye and not home_bye:
        lean += BYE_LEAN_POINTS
    return round(lean * 2) / 2


def _blend_with_ap(triples):
    present = [r for _, r, _ in triples if r is not None]
    lo, hi = (min(present), max(present)) if present else (0.0, 0.0)
    span = (hi - lo) or 1.0
    blended = []
    for team_id, rating, rank in triples:
        if rating is None or not rank:
            blended.append((team_id, rating))
            continue
        rank_component = hi - (rank - 1) * span / 49
        blended.append((team_id, (1 - AP_BLEND_WEIGHT) * rating + AP_BLEND_WEIGHT * rank_component))
    return blended


def _store_team_ratings(con, season, as_of, rows):
    for r in rows:
        con.execute(
            """INSERT INTO team_ratings (team_id, season, as_of_date, rating, offense, defense, games,
                    offense_rank, defense_rank, offense_grade, defense_grade, combined_rank, ap_rank,
                    blended_rating, power_rank, trend, ranking_scope, ranking_population)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(team_id, season, as_of_date) DO UPDATE SET
                    rating=excluded.rating, offense=excluded.offense, defense=excluded.defense, games=excluded.games,
                    offense_rank=excluded.offense_rank, defense_rank=excluded.defense_rank,
                    offense_grade=excluded.offense_grade, defense_grade=excluded.defense_grade,
                    combined_rank=excluded.combined_rank, ap_rank=excluded.ap_rank,
                    blended_rating=excluded.blended_rating, power_rank=excluded.power_rank, trend=excluded.trend,
                    ranking_scope=excluded.ranking_scope, ranking_population=excluded.ranking_population""",
            (r['id'], season, as_of.isoformat(), r['rating'], r['offense'], r['defense'], r['games'],
             r['offense_rank'], r['defense_rank'], r['offense_grade'], r['defense_grade'], r['combined_rank'],
             r['ap_rank'], r['blended_rating'], r['power_rank'], r['trend'], r.get('ranking_scope'), r.get('ranking_population')))
    con.commit()


def _prior_snapshot(con, season, as_of):
    """Most recent stored team_ratings snapshot strictly before as_of.

    Deliberate change from the live app: that version refit the model
    retroactively for every elapsed week on every single run (cheap early in
    a season, O(weeks) and growing worse every week thereafter). This reads
    the last *already-computed* run's ranks instead, so trend arrows come
    from real history the pipeline itself accumulates going forward.
    """
    row = con.execute(
        'SELECT MAX(as_of_date) AS d FROM team_ratings WHERE season=? AND as_of_date < ?',
        (season, as_of.isoformat())).fetchone()
    if not row or not row['d']:
        return None
    ranks = {r['team_id']: r['power_rank'] for r in con.execute(
        'SELECT team_id, power_rank FROM team_ratings WHERE season=? AND as_of_date=?', (season, row['d'])).fetchall()}
    return {'as_of': row['d'], 'ranks': ranks}


def build(season: int, as_of: date, use_priors: bool = True) -> dict:
    """Compute ratings + per-game projections/notes for `season` as of `as_of`,
    and persist them to team_ratings/game_notes/projections. Returns a summary.
    """
    with connect() as con:
        names = _fetch_team_names(con)
        fbs_names = _fetch_fbs_names(con)
        combined = _fetch_ranks(con, season, 'combined')
        ap_ranks = _fetch_ranks(con, season, 'ap')
        events = _fetch_season_games(con, season)
        weather_rows = {r['game_id']: dict(r) for r in con.execute('SELECT * FROM weather')}

        by_team = {}
        for x in events:
            for tid in (x['home_id'], x['away_id']):
                by_team.setdefault(tid, []).append(x)
        team_games = lambda tid: by_team.get(tid, [])

        completed_rows = _fetch_completed_rows(con, [season - 1, season], as_of)
        model = (Model(pooled_rows(completed_rows, names, fbs_names), as_of, ridge=MODEL_RIDGE, half_life=MODEL_HALF_LIFE)
                 if completed_rows else None)
        ratings = {r['team']: r for r in model.ratings()} if model else {}

        spend = nil_prior.load(season) if use_priors else {}
        talent = talent_prior.load(season) if use_priors else {}
        off_rates = officiating_prior.load_rates(season) if use_priors else {}

        spend_fits = nil_prior.fit(spend, ratings, names) if spend else None
        off_fit = officiating_prior.fit(ratings, off_rates) if off_rates else None
        talent_fit = talent_prior.fit(talent, ratings, names) if talent else None

        season_games = {}
        for x in events:
            if x.get('completed') and x['game_date'] < as_of.isoformat():
                for tid in (x['home_id'], x['away_id']):
                    season_games[tid] = season_games.get(tid, 0) + 1

        top_ratings = []
        for tid, rank in combined.items():
            r = ratings.get(tid)
            top_ratings.append({'id': tid, 'team': names.get(tid, tid), 'combined_rank': rank, 'ap_rank': ap_ranks.get(tid),
                                 'rating': r['rating'] if r else None, 'offense': r['offense'] if r else None,
                                 'defense': r['defense'] if r else None, 'games': r['games'] if r else 0,
                                 'ats': ats_record(team_games(tid), tid, as_of)})

        peer_ids = {tid for tid in ratings if fbs_key(names.get(tid, '')) in fbs_names} if fbs_names else set(ratings)
        peers = [ratings[tid] for tid in peer_ids]
        offense_pool = [r['offense'] for r in peers]
        defense_pool = [r['defense'] for r in peers]
        scope = 'FBS' if fbs_names else 'rated'
        for r in top_ratings:
            for metric in ('offense', 'defense'):
                r[metric + '_rank'] = None if r[metric] is None or r['id'] not in peer_ids else 1 + sum(t[metric] > r[metric] for t in peers)
            r['offense_grade'] = letter_grade(r['offense'], offense_pool)
            r['defense_grade'] = letter_grade(r['defense'], defense_pool)

        blended = dict(_blend_with_ap([(r['id'], r['rating'], r['ap_rank'] or r['combined_rank']) for r in top_ratings]))
        for r in top_ratings:
            r['blended_rating'] = blended.get(r['id'])
        top_ratings.sort(key=lambda r: (r['blended_rating'] is None, -(r['blended_rating'] if r['blended_rating'] is not None else 0), r['team']))
        for i, r in enumerate(top_ratings, 1):
            r['power_rank'] = i

        prior = _prior_snapshot(con, season, as_of)
        for r in top_ratings:
            if r['rating'] is None:
                r['trend'] = None
            elif not prior or prior['ranks'].get(r['id']) is None:
                r['trend'] = 'new'
            else:
                r['trend'] = str(prior['ranks'][r['id']] - r['power_rank'])
            r['ranking_scope'] = scope
            r['ranking_population'] = len(peers)

        # Every FBS-rated team gets an offense/defense grade for its matchup
        # cards, not just the combined Top 50 (that's the Power Ranking table's
        # own scope). Without this, any game involving a team outside the
        # Top 50 wrongly shows "Outside FBS ranking pool" even though the
        # model rates it -- see the ratings/power.py-vs-original-power.py note.
        top_ids = {r['id'] for r in top_ratings}
        extra_rows = []
        for tid in peer_ids - top_ids:
            r = ratings[tid]
            extra_rows.append({'id': tid, 'team': names.get(tid, tid), 'combined_rank': None, 'ap_rank': ap_ranks.get(tid),
                                'rating': r['rating'], 'offense': r['offense'], 'defense': r['defense'], 'games': r['games'],
                                'offense_rank': 1 + sum(t['offense'] > r['offense'] for t in peers),
                                'defense_rank': 1 + sum(t['defense'] > r['defense'] for t in peers),
                                'offense_grade': letter_grade(r['offense'], offense_pool),
                                'defense_grade': letter_grade(r['defense'], defense_pool),
                                'blended_rating': None, 'power_rank': None, 'trend': None,
                                'ranking_scope': scope, 'ranking_population': len(peers)})

        _store_team_ratings(con, season, as_of, top_ratings + extra_rows)

        # Per-game projections + notes (_store_notes clears each side's prior rows first).
        for e in events:
            hid, aid = e['home_id'], e['away_id']
            away_notes = situational_notes(team_games(aid), aid, combined.get(hid), e['game_date'], combined)
            hostile = hostile_environment_note(names.get(hid, ''), e.get('neutral'))
            if hostile:
                away_notes.append(hostile)
            home_notes = situational_notes(team_games(hid), hid, combined.get(aid), e['game_date'], combined)
            rivalry = RIVALRIES.get(frozenset((normal(names.get(hid, '')), normal(names.get(aid, '')))))
            if rivalry:
                home_notes.append(rivalry)
                away_notes.append(rivalry)
            for side, tid, notes in (('home', hid, home_notes), ('away', aid, away_notes)):
                recent = [x for x in team_games(tid) if x.get('completed') and x['game_date'] < min(e['game_date'], as_of.isoformat())]
                if recent:
                    recent.sort(key=lambda x: x['game_date'])
                    last = recent[-1]
                    own = 'home' if last['home_id'] == tid else 'away'
                    other = 'away' if own == 'home' else 'home'
                    notes.append(f"Last result: {last[own + '_score']}–{last[other + '_score']} vs {names.get(last[other + '_id'], '')}")

            w = weather_rows.get(e['game_id'])
            wn = weather_note(w) if w else None
            venue = json.loads(e['venue_json'] or '{}')
            wa = weather_alert(w, venue.get('indoor')) if w else None

            home_model, away_model = pooled(hid, names, fbs_names), pooled(aid, names, fbs_names)
            hr, ar = ratings.get(home_model), ratings.get(away_model)
            proj = None
            if hr and ar:
                pooled_fcs = [side for side, mid in (('home', home_model), ('away', away_model)) if mid == POOLED_FCS]
                home_spend = nil_prior.spending(spend, names.get(hid, '')) if spend else None
                away_spend = nil_prior.spending(spend, names.get(aid, '')) if spend else None
                margin_shift, _ = nil_prior.margin_shift(spend_fits, home_spend, away_spend, hr['rating'], ar['rating'],
                                                          season_games.get(hid, 0), season_games.get(aid, 0)) if spend_fits else (0.0, None)
                off_shift = 0.0
                if off_fit and home_model == hid and away_model == aid:
                    off_shift = officiating_prior.margin_shift(off_fit, off_rates.get(hid), off_rates.get(aid), hr['rating'], ar['rating'])
                home_talent = talent_prior.lookup(talent, names.get(hid, '')) if talent else None
                away_talent = talent_prior.lookup(talent, names.get(aid, '')) if talent else None
                talent_shift = talent_prior.margin_shift(talent_fit, home_talent if home_model == hid else None,
                                                          away_talent if away_model == aid else None, hr['rating'], ar['rating'],
                                                          season_games.get(hid, 0), season_games.get(aid, 0)) if talent_fit else 0.0
                total_shift = margin_shift + off_shift + talent_shift
                hp, ap = model.predict({'home_team': home_model, 'away_team': away_model, 'neutral': bool(e.get('neutral')),
                                         'home_adjustment': total_shift / 2, 'away_adjustment': -total_shift / 2})
                fair_home_spread = round(ap - hp, 2)
                lean = power_lean(fair_home_spread, home_notes, away_notes)
                home_edge = None if e.get('home_spread') is None else round((hp - ap) + e['home_spread'], 2)
                lean_edge = None if e.get('home_spread') is None else round(e['home_spread'] - lean, 2)
                total_edge = None if e.get('total') is None else round((hp + ap) - e['total'], 2)
                sample = min(season_games.get(hid, 0), season_games.get(aid, 0))
                lean_side = None if lean_edge is None or abs(lean_edge) < 1 else ('Home' if lean_edge > 0 else 'Away')
                if lean_edge is None:
                    confidence = 'Unavailable'
                elif sample < 2 or abs(lean_edge) < 2:
                    confidence = 'Low'
                elif sample < 5 or abs(lean_edge) < 4:
                    confidence = 'Moderate'
                else:
                    confidence = 'High'
                proj = {'home_points': round(hp, 1), 'away_points': round(ap, 1), 'fair_home_spread': fair_home_spread,
                        'projected_total': round(hp + ap, 1), 'lean_home_spread': lean, 'lean_source': 'model',
                        'lean_side': lean_side, 'home_edge_points': home_edge, 'lean_edge_points': lean_edge,
                        'total_edge_points': total_edge, 'sample_games': sample, 'confidence': confidence,
                        'confidence_detail': f'{sample} current-season completed games for the less-observed team. Qualitative confidence; not a calibrated cover probability.',
                        'spend_margin_shift': margin_shift, 'officiating_margin_shift': off_shift, 'talent_margin_shift': talent_shift,
                        'pooled_fcs_json': json.dumps(pooled_fcs)}
            else:
                proj = {'lean_source': 'unavailable', 'confidence': 'Unavailable', 'lean_side': None}

            _store_notes(con, e['game_id'], 'home', home_notes)
            _store_notes(con, e['game_id'], 'away', away_notes)
            if w:
                con.execute('UPDATE weather SET alert_text=?, lean_note=? WHERE game_id=?', (wa, wn, e['game_id']))
            _store_projection(con, e['game_id'], proj)
        con.commit()

    fit_count = len(completed_rows)
    fcs = ratings.get(POOLED_FCS)
    status = build_status(fit_count, spend_fits, off_fit, talent_fit, fcs, scope)
    return {'as_of': as_of.isoformat(), 'season': season, 'fit_games': fit_count, 'teams_rated': len(ratings),
            'games_projected': sum(1 for e in events), 'status': status}


def _store_notes(con, game_id, side, notes):
    con.execute('DELETE FROM game_notes WHERE game_id=? AND side=?', (game_id, side))
    for i, n in enumerate(notes):
        con.execute('INSERT INTO game_notes (game_id, side, note_order, note_text) VALUES (?,?,?,?)', (game_id, side, i, n))


def _store_projection(con, game_id, proj):
    now = datetime.now().astimezone().isoformat(timespec='seconds')
    con.execute(
        """INSERT INTO projections (game_id, home_points, away_points, fair_home_spread, projected_total,
                lean_home_spread, lean_source, lean_side, home_edge_points, lean_edge_points, total_edge_points,
                sample_games, confidence, confidence_detail, spend_margin_shift, officiating_margin_shift,
                talent_margin_shift, pooled_fcs_json, generated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(game_id) DO UPDATE SET
                home_points=excluded.home_points, away_points=excluded.away_points,
                fair_home_spread=excluded.fair_home_spread, projected_total=excluded.projected_total,
                lean_home_spread=excluded.lean_home_spread, lean_source=excluded.lean_source,
                lean_side=excluded.lean_side, home_edge_points=excluded.home_edge_points,
                lean_edge_points=excluded.lean_edge_points, total_edge_points=excluded.total_edge_points,
                sample_games=excluded.sample_games, confidence=excluded.confidence,
                confidence_detail=excluded.confidence_detail, spend_margin_shift=excluded.spend_margin_shift,
                officiating_margin_shift=excluded.officiating_margin_shift, talent_margin_shift=excluded.talent_margin_shift,
                pooled_fcs_json=excluded.pooled_fcs_json, generated_at=excluded.generated_at""",
        (game_id, proj.get('home_points'), proj.get('away_points'), proj.get('fair_home_spread'),
         proj.get('projected_total'), proj.get('lean_home_spread'), proj.get('lean_source'), proj.get('lean_side'),
         proj.get('home_edge_points'), proj.get('lean_edge_points'), proj.get('total_edge_points'),
         proj.get('sample_games'), proj.get('confidence'), proj.get('confidence_detail'),
         proj.get('spend_margin_shift'), proj.get('officiating_margin_shift'), proj.get('talent_margin_shift'),
         proj.get('pooled_fcs_json'), now))


def build_status(fit_count, spend_fits, off_fit, talent_fit, fcs, scope):
    status = (f'Fit on {fit_count} completed FBS games. Offense and defense ranks/grades compare {scope} teams only. '
              f'Previous-season scores are included when available, with recency weighting ({MODEL_HALF_LIFE:.0f}-day half-life). '
              'Predictions use opponent-adjusted scoring, home/neutral venue and rest/lookahead context. '
              'Confidence is qualitative and has not been calibrated as a cover probability.')
    if fcs:
        status += (f" Every FCS opponent shares one pooled rating drawn from {fcs['games']} games against FBS teams.")
    if spend_fits and spend_fits.get('roster_cost'):
        roster_fit = spend_fits['roster_cost']
        status += (f" A roster-cost prior nudges the projected margin while a team has under {nil_prior.FADE_GAMES} games "
                   f"this season (fitted this refresh at {roster_fit['points_per_doubling']} pts per doubling of payroll, "
                   f"R² {roster_fit['r_squared']}).")
    if off_fit:
        status += (f" A penalty-tendency prior (fitted this refresh at {off_fit['slope']} pts of margin per penalty of net "
                   f"differential, R² {off_fit['r_squared']} across {off_fit['teams']} teams) nudges the margin.")
    if talent_fit:
        status += (f" A roster-talent prior from 247Sports (fitted this refresh at {talent_fit['slope']} rating pts per point "
                   f"of average player rating, R² {talent_fit['r_squared']} across {talent_fit['teams']} teams) pulls each "
                   f"FBS team toward the rating its roster implies.")
    return status


if __name__ == '__main__':
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument('season', type=int)
    p.add_argument('--as-of', type=date.fromisoformat, default=date.today())
    a = p.parse_args()
    print(json.dumps(build(a.season, a.as_of), indent=2))
