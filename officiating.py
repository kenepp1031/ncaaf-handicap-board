"""Team-level penalty tendency, and a penalty-based prior on projected margin.

No public source ties a specific referee to a specific NCAA football game --
not before kickoff, and (checked directly) not even after one: ESPN's own
game summary carries no officiating crew, and the two sites that publish any
penalty analytics (refmetrics.com) gate essentially everything behind a paid
account, including which official worked which game. So "referee" tendency
here is really a *team* tendency: how many penalties/yards a team's games
have run, split by whether it was flagged or benefited, and home vs away.
That is available for free from ESPN's own box scores -- the same source
feeds.py already reads -- one summary call per completed game.

Like nil.py's spending prior, the margin adjustment here is fitted fresh each
refresh (team rating regressed on each team's net penalty differential) rather
than assumed, so a non-predictive relationship makes the slope come out near
zero and the adjustment disappears on its own. Unlike spending, this is not an
early-season stand-in for talent -- it is a persistent situational tendency --
so its weight grows with sample size instead of fading as the season goes on.

Set MAX_WEIGHT to 0 to disable the adjustment entirely.
"""
import json
import time
from concurrent.futures import ThreadPoolExecutor

from feeds import ESPN, fetch

CACHE_NAME = 'penalties.json'
SUMMARY = ESPN+'summary?event={}'
FETCH_BUDGET_SECONDS = 40
FETCH_WORKERS = 6

# Weight given to the penalty prior, scaled up from 0 to MAX_WEIGHT as a team
# accumulates penalty-sample games, reaching full weight at FULL_SAMPLE_GAMES.
MAX_WEIGHT = 0.15
FULL_SAMPLE_GAMES = 6
MIN_FIT_TEAMS = 20


def load(folder):
    path = folder/CACHE_NAME
    try:
        stored = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}
    return stored if isinstance(stored, dict) else {}


def _save(folder, cache):
    path = folder/CACHE_NAME
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(cache, indent=2), encoding='utf-8')
    temp.replace(path)


def _extract(summary):
    stats = {s['homeAway']: s['statistics'] for s in summary.get('boxscore', {}).get('teams', [])}

    def penalties(side):
        row = next((s for s in stats.get(side, []) if s.get('name') == 'totalPenaltiesYards'), None)
        if not row or '-' not in str(row.get('displayValue', '')):
            return None, None
        count, yards = row['displayValue'].split('-', 1)
        try:
            return int(count), int(yards)
        except ValueError:
            return None, None

    home_count, home_yards = penalties('home')
    away_count, away_yards = penalties('away')
    if home_count is None or away_count is None:
        return None
    return {'home_penalties': home_count, 'home_penalty_yards': home_yards,
            'away_penalties': away_count, 'away_penalty_yards': away_yards}


def refresh(events, folder, budget_seconds=FETCH_BUDGET_SECONDS):
    """Fetch box-score penalty counts for completed games the cache is missing.

    Permanent cache: a finished game's penalty count never changes, so this
    only ever fetches forward. A time budget (like feeds.py's DK pages) keeps
    one refresh from blocking on a large backlog; the rest fills in over
    subsequent refreshes.
    """
    cache = load(folder)
    missing = [e['id'] for e in events if e.get('completed') and e['id'] not in cache]
    if not missing:
        return cache
    deadline = time.monotonic()+budget_seconds
    fetched, failures = 0, 0

    def pull(event_id):
        data = json.loads(fetch(SUMMARY.format(event_id)))
        return event_id, _extract(data)

    with ThreadPoolExecutor(max_workers=FETCH_WORKERS) as pool:
        for event_id, result in pool.map(pull, missing):
            if result:
                cache[event_id] = result
                fetched += 1
            else:
                failures += 1
            if time.monotonic() >= deadline:
                break
    if fetched:
        _save(folder, cache)
    return cache


def team_rates(events, cache):
    """Per-team penalty tendency: own penalties and penalties drawn, per game.

    `own` is penalties committed by the team; `drawn` is penalties on the
    opponent in that same game (a proxy for calls that ran the team's way).
    Both are also split by home/away since a team's own discipline and how a
    crew treats it at home need not be the same thing.
    """
    totals = {}
    for e in events:
        row = cache.get(e['id'])
        if not e.get('completed') or not row:
            continue
        for side, other in (('home', 'away'), ('away', 'home')):
            tid = e[side+'_id']
            t = totals.setdefault(tid, {'games': 0, 'own': 0, 'own_yards': 0, 'drawn': 0, 'drawn_yards': 0,
                                         'home_games': 0, 'home_own': 0, 'away_games': 0, 'away_own': 0})
            t['games'] += 1
            t['own'] += row[side+'_penalties']
            t['own_yards'] += row[side+'_penalty_yards']
            t['drawn'] += row[other+'_penalties']
            t['drawn_yards'] += row[other+'_penalty_yards']
            t[side+'_games'] += 1
            t[side+'_own'] += row[side+'_penalties']
    rates = {}
    for tid, t in totals.items():
        rates[tid] = {'games': t['games'],
                      'penalties_per_game': round(t['own']/t['games'], 2),
                      'penalty_yards_per_game': round(t['own_yards']/t['games'], 1),
                      'drawn_per_game': round(t['drawn']/t['games'], 2),
                      'net_penalty_margin': round(t['drawn']/t['games']-t['own']/t['games'], 2),
                      'home_penalties_per_game': round(t['home_own']/t['home_games'], 2) if t['home_games'] else None,
                      'away_penalties_per_game': round(t['away_own']/t['away_games'], 2) if t['away_games'] else None}
    return rates


def _least_squares(pairs):
    if len(pairs) < MIN_FIT_TEAMS:
        return None
    xs, ys = [x for x, _ in pairs], [y for _, y in pairs]
    mean_x, mean_y = sum(xs)/len(xs), sum(ys)/len(ys)
    sxx = sum((x-mean_x)**2 for x in xs)
    if sxx <= 0:
        return None
    slope = sum((x-mean_x)*(y-mean_y) for x, y in pairs)/sxx
    intercept = mean_y-slope*mean_x
    total = sum((y-mean_y)**2 for y in ys)
    residual = sum((y-(intercept+slope*x))**2 for x, y in pairs)
    return {'slope': round(slope, 4), 'intercept': round(intercept, 4), 'teams': len(pairs),
            'r_squared': round(1-residual/total, 4) if total else 0.0}


def fit(ratings, rates):
    """Fit team rating against net penalty margin (drawn minus own, per game).

    Returns None when there isn't enough overlap to say anything, leaving the
    model exactly as it was -- same contract as nil.fit.
    """
    pairs = [(rates[tid]['net_penalty_margin'], r['rating'])
             for tid, r in ratings.items() if tid in rates and r.get('rating') is not None]
    return _least_squares(pairs)


def weight(games):
    """How much to trust the penalty prior: grows with sample size, unlike
    spending's fade -- this is a standing tendency, not a talent stand-in that
    results supersede."""
    if not games or MAX_WEIGHT <= 0:
        return 0.0
    return MAX_WEIGHT*min(1.0, games/FULL_SAMPLE_GAMES)


def team_shift(fitted, rate, rating):
    if not fitted or not rate or rating is None:
        return 0.0
    w = weight(rate['games'])
    if w <= 0:
        return 0.0
    implied = fitted['intercept']+fitted['slope']*rate['net_penalty_margin']
    return round(w*(implied-rating), 3)


def margin_shift(fitted, home_rate, away_rate, home_rating, away_rating):
    """Points to move the projected margin, positive toward the home side."""
    if not fitted:
        return 0.0
    home = team_shift(fitted, home_rate, home_rating)
    away = team_shift(fitted, away_rate, away_rating)
    return round(home-away, 2)
