"""Opponent-adjusted scoring model. Confidence is qualitative, not a win probability."""
from datetime import date
from handicap import Model
from feeds import normal
import nil

MIN_GAMES = 2
BYE_REST_DAYS = 12
WIND_LEAN_MPH = 15
RAIN_LEAN_IN = 0.05
LETDOWN_LEAN_POINTS = 1.5
LOOKAHEAD_LEAN_POINTS = 1.0
BYE_LEAN_POINTS = 1.0
# Percentile cutoffs (0=worst, 1=best among this week's fitted teams) for a
# report-card letter grade, self-calibrated the same way as the AP blend so
# it needs no fixed point scale. A team sitting at or above a cutoff gets
# that grade; ties and small pools land on the coarser end deliberately.
GRADE_CUTOFFS = [(0.95, 'A+'), (0.85, 'A'), (0.75, 'A-'), (0.65, 'B+'), (0.55, 'B'), (0.45, 'B-'),
                  (0.35, 'C+'), (0.25, 'C'), (0.15, 'C-'), (0.08, 'D')]


def letter_grade(value, population):
    """Percentile-based letter grade using the same FBS population as numeric ranks."""
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
AP_BLEND_WEIGHT = 0.4

# Combined rank (average of ESPN's Top 25 and RotoBaller's top 10 + honorable
# mentions, ties broken alphabetically) and venue name. See module docstring.
HOSTILE_ENVIRONMENTS = {
    'lsu': (1, 'Tiger Stadium'),
    'ucla': (2, 'Rose Bowl'),
    'pennstate': (3, 'Beaver Stadium'),
    'michigan': (4, 'Michigan Stadium'),
    'washington': (5, 'Husky Stadium'),
    'alabama': (6, 'Bryant-Denny Stadium'),
    'tennessee': (7, 'Neyland Stadium'),
    'ohiostate': (8, 'Ohio Stadium'),
    'notredame': (9, 'Notre Dame Stadium'),
    'texasam': (10, 'Kyle Field'),
    'clemson': (11, 'Memorial Stadium'),
    'wisconsin': (12, 'Camp Randall Stadium'),
    'army': (13, 'Michie Stadium'),
    'florida': (14, 'Ben Hill Griffin Stadium'),
    'nebraska': (15, 'Memorial Stadium'),
    'virginiatech': (16, 'Lane Stadium'),
    'floridastate': (17, 'Doak Campbell Stadium'),
    'oregon': (18, 'Autzen Stadium'),
    'georgia': (19, 'Sanford Stadium'),
    'auburn': (20, 'Jordan-Hare Stadium'),
    'olemiss': (21, 'Vaught-Hemingway Stadium'),
    'texas': (22, 'Darrell K Royal–Texas Memorial Stadium'),
    'usc': (23, 'Los Angeles Memorial Coliseum'),
    'appalachianstate': (24, 'Kidd Brewer Stadium'),
    'oklahoma': (25, 'Gaylord Family Oklahoma Memorial Stadium'),
}


def hostile_environment_note(home_team, neutral):
    """Flag a true road game at one of the toughest combined-rank environments."""
    if neutral:
        return None
    hit = HOSTILE_ENVIRONMENTS.get(normal(home_team))
    if not hit:
        return None
    rank, venue = hit
    return f'Road game at {venue} — hostile environment #{rank}'


def _row(e):
    return {'date': date.fromisoformat(e['game_date']), 'home_team': e['home_id'], 'away_team': e['away_id'],
            'neutral': bool(e.get('neutral')), 'home_score': float(e['home_score']), 'away_score': float(e['away_score'])}


def _completed_before(events, as_of):
    return [_row(e) for e in events if e.get('completed') and e.get('home_score') is not None and e.get('away_score') is not None
            and date.fromisoformat(e['game_date']) < as_of]


def ats_record(events, team_id, before):
    """Wins/losses/pushes against ESPN's closing spread this season, for one team."""
    record = {'wins': 0, 'losses': 0, 'pushes': 0}
    for e in events:
        if not e.get('completed') or e.get('home_score') is None or e.get('home_spread') is None:
            continue
        if date.fromisoformat(e['game_date']) >= before:
            continue
        if e['home_id'] == team_id:
            margin, spread = e['home_score']-e['away_score'], e['home_spread']
        elif e['away_id'] == team_id:
            margin, spread = e['away_score']-e['home_score'], -e['home_spread']
        else:
            continue
        covered = margin+spread
        record['pushes' if covered == 0 else ('wins' if covered > 0 else 'losses')] += 1
    return record


def opponent(e, team_id):
    return e['away_id'] if e['home_id'] == team_id else e['home_id']


def _neighbors(events, team_id, game_date):
    played = sorted((e for e in events if team_id in (e['home_id'], e['away_id'])), key=lambda e: e['game_date'])
    before = [e for e in played if e['game_date'] < game_date]
    after = [e for e in played if e['game_date'] > game_date]
    return (before[-1] if before else None), (after[0] if after else None)


def situational_notes(events, team_id, this_week_opp_rank, game_date, combined):
    notes = []
    last_game, next_game = _neighbors(events, team_id, game_date)
    if last_game:
        rest = (date.fromisoformat(game_date)-date.fromisoformat(last_game['game_date'])).days
        if rest >= BYE_REST_DAYS:
            notes.append(f'Off a bye ({rest} days rest)')
        if last_game.get('completed') and last_game.get('home_score') is not None:
            side = 'home' if last_game['home_id'] == team_id else 'away'
            other = 'away' if side == 'home' else 'home'
            won = last_game[side+'_score'] > last_game[other+'_score']
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


def weather_note(e):
    w = e.get('weather')
    if not w or w.get('wind_speed_10m') is None:
        return None
    if w['wind_speed_10m'] >= WIND_LEAN_MPH or (w.get('precipitation') or 0) >= RAIN_LEAN_IN:
        return f"Wind {round(w['wind_speed_10m'])} mph / rain {w.get('precipitation') or 0:g} in — guides lean Under in these spots"
    return None


def _has(notes, prefix):
    return any(n.startswith(prefix) for n in notes)


def power_lean(fair_home_spread, home_notes, away_notes):
    """Nudge the model's fair home spread for the situational notes already shown,
    then round to the nearest half point (the standard sportsbook increment).

    This is a deliberate nudge on top of the model's own projection, not a
    second independent forecast: a letdown or lookahead flag works against
    that side (see *_LEAN_POINTS above); extra rest from a bye helps whichever
    side has it, if only one side does; stadium reputation is informational only, since the model already includes home field. Follows the same home-team-spread convention as the market:
    negative means the home team is favored.
    """
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


def weather_alert(e):
    """Outdoor game-window alerts; mixed/freezing precipitation includes sleet risk."""
    w = e.get('weather')
    if not w or e.get('venue', {}).get('indoor'):
        return None
    reasons = []
    codes = w.get('weather_codes', [w.get('weather_code')])
    if any(c in (56,57,66,67,68,69,79) for c in codes):
        reasons.append('freezing / mixed precipitation (sleet risk)')
    if (w.get('snowfall') or 0) > 0 or any(c in (71,73,75,77,85,86) for c in codes):
        reasons.append('snow')
    if (w.get('rain') or 0) > 0 or (w.get('precipitation') or 0) > 0 or any(c in (51,53,55,61,63,65,80,81,82,95,96,99) for c in codes):
        reasons.append('rain / precipitation')
    if (w.get('wind_speed_10m') or 0) >= 15:
        reasons.append(f"wind {round(w['wind_speed_10m'])} mph")
    if (w.get('wind_gusts_10m') or 0) >= 15:
        reasons.append(f"gusts {round(w['wind_gusts_10m'])} mph")
    return 'Game forecast: ' + ', '.join(reasons) if reasons else None


def _blend_with_ap(triples):
    """Blend each (team_id, rating, effective_rank) with a rank-derived prior.

    Early season, a handful of games can produce ridge ratings that read as
    "far off" from what everyone already expects. AP_BLEND_WEIGHT=0 would be
    the pure model, 1 would just replicate the rank order passed in.

    Pulling only AP-ranked teams *up* toward the model's own best-rated team
    doesn't work: that best-rated team is often someone AP hasn't ranked at
    all, and if it's left untouched it becomes a ceiling no AP team can ever
    cross, no matter how strongly AP feels about them — which is exactly the
    "still far off" complaint this exists to fix. So every team is blended:
    effective_rank should be the team's actual AP Top 25 rank when AP ranked
    it, or its combined Top 50 rank otherwise, so a team AP snubbed but
    CBS/Coaches still like isn't penalized as harshly as a true afterthought.
    Only a team with no ranking information at all (effective_rank is None)
    is left unblended. The prior's scale is self-calibrated from this week's
    own observed rating range across a 1-50 scale, so it needs no arbitrary
    point guess.
    """
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


def rating_history(payload, today):
    """Retroactively fit the power model as of the start of each past week.

    Because ratings are derived from games already played, this needs no
    separate snapshot job and is complete back to week 1 the first time it
    runs — unlike the combined poll ranking, which ESPN's public feed only
    ever exposes as the current snapshot (see dashboard.py's rank_history.json
    for that one, which can only track forward from when it starts running).
    """
    events = payload.get('events', [])
    combined_ranks = {t['id']: t['rank'] for t in payload.get('top50', [])}
    ap_ranks = payload.get('ap', {})
    weeks = sorted((w for w in payload.get('weeks', []) if w.get('type') == 2), key=lambda w: w['number'])
    snapshots = []
    for w in weeks:
        start = date.fromisoformat(w['start'][:10])
        if start > today:
            continue
        rows = _completed_before(payload.get('history_events', []) + events, start)
        if not rows:
            continue
        m = Model(rows, start)
        eligible = [r for r in m.ratings() if r['team'] in combined_ranks and r['games'] >= MIN_GAMES]
        triples = [(r['team'], r['rating'], ap_ranks.get(r['team']) or combined_ranks.get(r['team'])) for r in eligible]
        blended = _blend_with_ap(triples)
        ranked = sorted(blended, key=lambda pair: -pair[1])
        snapshots.append({'week': w['number'], 'label': w['label'], 'as_of': start.isoformat(),
                           'ranks': {team_id: i+1 for i, (team_id, _) in enumerate(ranked)}})
    return snapshots


# CBS's full FBS list identifies the comparison population; normalize its
# abbreviated school names without treating FCS opponents as FBS members.
FBS_ALIASES = dict(zip(
    'missstate ndakotast iowast sandiegost michiganst wmichigan coloradost washingtonst gasouthern jacksonvillest arkansasst appst fresnost texasst utahst kennesawst fau ccarolina fiu newmexicost somiss emichigan cmichigan georgiast sacramentost missourist middletenn kentst ballst sanjosstate'.split(),
    'mississippistate northdakotastate iowastate sandiegostate michiganstate westernmichigan coloradostate washingtonstate georgiasouthern jacksonvillestate arkansasstate appalachianstate fresnostate texasstate utahstate kennesawstate floridaatlantic coastalcarolina florida international southern easternmichigan centralmichigan georgiastate sacramentostate missouristate middletennessee kentstate ballstate sanjosestate'.split()))
FBS_ALIASES.update(fiu='floridainternational', newmexicost='newmexicostate', somiss='southernmiss')


def fbs_key(name):
    key = normal(name)
    return FBS_ALIASES.get(key, key)


def build(payload, as_of, spend=None):
    """Return power ratings and per-game notes for the cached season.

    Ratings use every completed FBS result before as_of, regardless of which
    week is being viewed, matching how the rest of the dashboard treats
    imported data (see README: the combined watchlist behaves the same way).

    `spend` is the cached school-spending tables. When supplied, a spending
    prior nudges the projected margin for teams the model has barely seen this
    season; see nil.py for why it is a prior and not a term in the spread.
    """
    events = payload.get('events', [])
    combined = {t['id']: t['rank'] for t in payload.get('top50', [])}
    ap_ranks = payload.get('ap', {})
    names = {}
    for e in events:
        names[e['home_id']] = e['home']
        names[e['away_id']] = e['away']
    completed_rows = _completed_before(payload.get('history_events', []) + events, as_of)
    model = Model(completed_rows, as_of) if completed_rows else None
    ratings = {r['team']: r for r in model.ratings()} if model else {}
    spend_fits = nil.fit(spend, ratings, names) if spend else None
    season_games = {}
    for x in events:
        if x.get('completed') and x['game_date'] < as_of.isoformat():
            for tid in (x['home_id'], x['away_id']):
                season_games[tid] = season_games.get(tid, 0)+1
    top_ratings = []
    for tid, rank in combined.items():
        r = ratings.get(tid)
        top_ratings.append({'id': tid, 'team': names.get(tid, tid), 'combined_rank': rank, 'ap_rank': ap_ranks.get(tid),
                             'rating': r['rating'] if r else None, 'offense': r['offense'] if r else None,
                             'defense': r['defense'] if r else None, 'games': r['games'] if r else 0,
                             'spending': nil.spending(spend, names.get(tid, '')) if spend else None,
                             'ats': ats_record(events, tid, as_of)})
    fbs_names = {fbs_key(n) for n in payload.get('cbs', {})}
    peer_ids = {tid for tid in ratings if fbs_key(names.get(tid,'')) in fbs_names} if fbs_names else set(ratings)
    peers = [ratings[tid] for tid in peer_ids]
    offense_pool = [r['offense'] for r in peers]
    defense_pool = [r['defense'] for r in peers]
    scope = 'FBS' if fbs_names else 'rated teams'
    for r in top_ratings:
        for metric in ('offense', 'defense'):
            r[metric+'_rank'] = None if r[metric] is None or r['id'] not in peer_ids else 1 + sum(t[metric] > r[metric] for t in peers)
        r['offense_grade'] = letter_grade(r['offense'], offense_pool)
        r['defense_grade'] = letter_grade(r['defense'], defense_pool)
    blended = dict(_blend_with_ap([(r['id'], r['rating'], r['ap_rank'] or r['combined_rank']) for r in top_ratings]))
    for r in top_ratings:
        r['blended_rating'] = blended.get(r['id'])
    top_ratings.sort(key=lambda r: (r['blended_rating'] is None, -(r['blended_rating'] if r['blended_rating'] is not None else 0), r['team']))
    for i, r in enumerate(top_ratings, 1):
        r['power_rank'] = i
    history = rating_history(payload, as_of)
    prior = history[-1] if history else None
    for r in top_ratings:
        if r['rating'] is None:
            r['trend'] = None
        elif not prior or prior['ranks'].get(r['id']) is None:
            r['trend'] = 'new'
        else:
            r['trend'] = prior['ranks'][r['id']] - r['power_rank']
    team_ratings = []
    for tid, r in ratings.items():
        t = dict(r, id=tid, ranking_scope=scope, ranking_population=len(peers), ranked=tid in peer_ids)
        for metric, pool in (('offense',offense_pool),('defense',defense_pool)):
            t[metric+'_rank'] = 1 + sum(v > r[metric] for v in pool) if tid in peer_ids else None
            t[metric+'_grade'] = letter_grade(r[metric],pool) if tid in peer_ids else None
        team_ratings.append(t)
    games = {}
    for e in events:
        if e.get('completed') or date.fromisoformat(e['game_date']) < as_of:
            continue
        hid, aid = e['home_id'], e['away_id']
        away_notes = situational_notes(events, aid, e.get('home_combined'), e['game_date'], combined)
        hostile = hostile_environment_note(e['home'], e.get('neutral'))
        if hostile:
            away_notes.append(hostile)
        entry = {'home_ats': ats_record(events, hid, as_of), 'away_ats': ats_record(events, aid, as_of),
                  'home_notes': situational_notes(events, hid, e.get('away_combined'), e['game_date'], combined),
                  'away_notes': away_notes}
        rivalry = {frozenset(('kansas','missouri')):'Border Showdown rivalry', frozenset(('iowa','iowastate')):'Cy-Hawk rivalry'}.get(frozenset((normal(e['home']),normal(e['away']))))
        if rivalry:
            entry['home_notes'].append(rivalry)
            entry['away_notes'].append(rivalry)
        for side, tid in (('home',hid),('away',aid)):
            recent = [x for x in events if x.get('completed') and tid in (x['home_id'],x['away_id']) and x['game_date'] < min(e['game_date'], as_of.isoformat())]
            if recent:
                recent.sort(key=lambda x:x['game_date'])
                last = recent[-1]
                own = 'home' if last['home_id']==tid else 'away'
                other = 'away' if own=='home' else 'home'
                entry[side+'_notes'].append(f"Last result: {last[own+'_score']}–{last[other+'_score']} vs {last[other]}")
        wn = weather_note(e)
        if wn:
            entry['weather_note'] = wn
        wa = weather_alert(e)
        if wa:
            entry['weather_alert'] = wa
        hr, ar = ratings.get(hid), ratings.get(aid)
        if hr and ar:
            home_spend = nil.spending(spend, e['home']) if spend else None
            away_spend = nil.spending(spend, e['away']) if spend else None
            margin_shift, spend_measure = nil.margin_shift(spend_fits, home_spend, away_spend, hr['rating'], ar['rating'],
                                                           season_games.get(hid, 0), season_games.get(aid, 0))
            entry.update(home_spending=home_spend, away_spending=away_spend,
                         spend_margin_shift=margin_shift, spend_measure=spend_measure)
            hp, ap = model.predict({'home_team': hid, 'away_team': aid, 'neutral': bool(e.get('neutral')),
                                     'home_adjustment': margin_shift/2, 'away_adjustment': -margin_shift/2})
            fair_home_spread = round(ap-hp, 2)
            lean = power_lean(fair_home_spread, entry['home_notes'], entry['away_notes'])
            entry.update(home_points=round(hp, 1), away_points=round(ap, 1), fair_home_spread=fair_home_spread,
                         projected_total=round(hp+ap, 1), lean_home_spread=lean, lean_source='model',
                         home_edge_points=None if e.get('home_spread') is None else round((hp-ap)+e['home_spread'], 2),
                         lean_edge_points=None if e.get('home_spread') is None else round(e['home_spread']-lean, 2),
                         total_edge_points=None if e.get('total') is None else round((hp+ap)-e['total'], 2))
        else:
            entry.update(lean_source='unavailable', confidence='Unavailable', lean_side=None)
        if hr and ar:
            sample = min(season_games.get(hid, 0), season_games.get(aid, 0))
            edge = entry.get('lean_edge_points')
            entry['sample_games'] = sample
            entry['lean_side'] = None if edge is None or abs(edge) < 1 else ('Home' if edge > 0 else 'Away')
            entry['confidence'] = ('Unavailable' if edge is None else 'Low' if sample < 4 or abs(edge) < 3 else 'Moderate')
            entry['confidence_detail'] = f'{sample} current-season completed games for the less-observed team. Qualitative confidence; not a calibrated cover probability.'
        games[e['id']] = entry
    fit_count = len(completed_rows)
    thin = sum(1 for r in top_ratings if r['games'] < MIN_GAMES)
    status = (f'Fit on {fit_count} completed FBS games. Offense and defense ranks/grades compare rated FBS teams only; FCS opponents are excluded from the ranking pool. Previous-season scores are included when available, with recency weighting (180-day half-life). '
              'Predictions use opponent-adjusted scoring, home/neutral venue and rest/lookahead context. '
              'Early-season confidence is Low; no ATS lean without both team histories and a market spread. '
              'Confidence is qualitative and has not been calibrated as a cover probability.')
    if spend_fits and spend_fits.get('roster'):
        roster_fit = spend_fits['roster']
        status += (f" A roster-cost prior nudges the projected margin while a team has under {nil.FADE_GAMES} games this season "
                   f"(fitted this refresh at {roster_fit['points_per_doubling']} pts per doubling of payroll, R² {roster_fit['r_squared']}); it fades to zero after that "
                   'and is skipped unless both schools report a roster cost. Athletic department budgets are listed for reference and never move a spread.')
    return {'as_of': as_of.isoformat(), 'min_games': MIN_GAMES, 'status': status, 'ratings': top_ratings, 'team_ratings': team_ratings, 'ranking_population':len(peers), 'ranking_scope':scope, 'games': games,
            'trend_since': prior['label'] if prior else None, 'history_weeks_tracked': len(history),
            'spend_fit': spend_fits, 'spend_board': nil.leaderboard(spend) if spend else None,
            'spend_labels': (spend or {}).get('labels'),
            'spend_source': (spend or {}).get('source'), 'spend_fetched_at': (spend or {}).get('fetched_at'),
            'spend_fade_games': nil.FADE_GAMES}
