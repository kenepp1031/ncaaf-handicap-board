"""Roster talent from 247Sports' Team Talent Composite, and a talent prior on team strength.

247Sports rates every player on each FBS roster by his recruiting grade and
publishes one row per school: how many rated players it carries, its 5-, 4- and
3-star counts, their average rating and a weighted talent score. That is the
rosters-and-player-rankings view of a program, from one public page -- three
requests of fifty schools each, no account or key.

How it moves a spread
---------------------
Like the roster-cost prior in nil.py, the slope is fitted fresh each refresh
(team rating regressed on average player rating), never assumed, and each FBS
team is pulled MAX_WEIGHT of the way toward the rating its roster implies. The
pull is full before a team has played and fades to exactly zero at FADE_GAMES
current-season results. It moves the margin only. Unlike roster cost, each side
is judged on its own, so an FCS opponent with no composite row simply sits out
while its FBS opponent is still measured.

Chosen by walk-forward test, the same way as the model's ridge and half-life:
every 2025 game predicted only from games before its week, using 2025's
composite, then confirmed once on 2026's first 100 games, which the choice
never saw. Mean absolute margin error:
    2025 (958 games)   12.665 -> 12.649   no measurable change (-0.016 +/- 0.029)
    2026 holdout       17.200 -> 16.892   -0.31 +/- 0.18
Against the week of Sept. 12's 84 DraftKings lines it made no net difference
once every other adjustment is in (mean gap 6.57 -> 6.58): closer on FBS-vs-FCS
games, further on FBS-vs-FBS ones. Average rating beat
the weighted talent score, its log, adding 247's transfer-portal class, and
last season's talent change (roster turnover, which made 2025 worse). A weight
of 0.2 was an interior optimum on 2025 (0.1 and 0.35 both worse); heavier
weights did better on 2026's sample, which is too small to tune on.

The 2026 composite grades players on 247's own high-school ratings, not the
industry composite or a transfer grade. Set MAX_WEIGHT to 0 to turn the prior
off and leave the model unchanged.
"""
import json
import re
import urllib.request
from datetime import datetime

from feeds import clean, normal

SOURCE = 'https://247sports.com/season/{season}-football/collegeteamtalentcomposite/'
# The page lists fifty schools; its Load More button asks for the next fifty here.
PAGE_QUERY = '?ViewPath=~%2FViews%2FSkyNet%2FInstitutionRanking%2F_SimpleSetForSeason.ascx&Page={page}'
CACHE_NAME = 'talent.json'
AGENT = {'User-Agent': 'Mozilla/5.0 (compatible; cfb-handicap/1.0)'}
MAX_PAGES = 6
# FBS has 136+ schools; fewer means the layout changed or the season's
# composite is not published yet (it appears in late summer).
MIN_SCHOOLS = 100

MAX_WEIGHT = 0.2
FADE_GAMES = 8
MIN_FIT_TEAMS = 20

# Schools whose 247 and ESPN spellings still differ once punctuation (and
# ESPN's accented é) is stripped.
ALIASES = {'sanjosstate': 'sanjosestate', 'louisianamonroe': 'ulmonroe', 'fiu': 'floridainternational'}


def key(name):
    plain = normal(name or '')
    return ALIASES.get(plain, plain)


def _number(fragment):
    found = re.search(r'-?\d+(?:\.\d+)?', clean(fragment or '').replace(',', ''))
    return float(found[0]) if found else None


def parse(page):
    """One row per school from a composite page or one of its Load More pages."""
    rows = []
    for chunk in page.split('<li class="rankings-page__list-item">')[1:]:
        # Each row ends where its player flyout begins; anything later is the
        # next row or the page footer.
        chunk = chunk.split('data-react-container', 1)[0]
        fields = {name: re.search(r'class="%s">(.*?)</div>' % name, chunk, re.S)
                  for name in ('primary', 'total', 'avg', 'points')}
        link = re.search(r'class="rankings-page__name-link"[^>]*>(.*?)</a>', chunk, re.S)
        team = clean(link[1]) if link else ''
        average = _number(fields['avg'][1]) if fields['avg'] else None
        if not team or average is None:
            continue
        value = lambda name: _number(fields[name][1]) if fields[name] else None
        stars = {int(s): int(n) for s, n in re.findall(r'<h2>(\d)-Star</h2>\s*<div[^>]*>\s*(\d+)', chunk)}
        rank, players = value('primary'), value('total')
        rows.append({'team': team, 'rank': None if rank is None else int(rank), 'points': value('points'),
                     'avg_rating': average, 'players': None if players is None else int(players),
                     'five_star': stars.get(5, 0), 'four_star': stars.get(4, 0), 'three_star': stars.get(3, 0)})
    return rows


def _get(url):
    request = urllib.request.Request(url, headers=AGENT)
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read().decode('utf-8', 'replace')


def fetch_season(season, get=_get):
    """Every school on the season's composite, following Load More until it adds nobody."""
    base = SOURCE.format(season=season)
    schools = {}
    for page in range(1, MAX_PAGES+1):
        new = [r for r in parse(get(base if page == 1 else base+PAGE_QUERY.format(page=page)))
               if key(r['team']) not in schools]
        if not new:
            break
        for row in new:
            schools[key(row['team'])] = row
    if len(schools) < MIN_SCHOOLS:
        raise ValueError(f'247Sports talent composite returned {len(schools)} schools: layout changed or not yet published')
    return {'source': base, 'season': season, 'fetched_at': datetime.now().astimezone().isoformat(timespec='seconds'),
            'schools': schools}


def load(data):
    try:
        stored = json.loads((data/CACHE_NAME).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}
    return stored if isinstance(stored, dict) else {}


def refresh(data, season, force=False, max_age_days=7, get=_get):
    """This season's composite, cached for a week. Another season's copy is never
    used: rosters turn over, which is exactly what this is here to measure."""
    stored = load(data)
    current = stored if stored.get('season') == season and stored.get('schools') else {}
    if current and not force:
        try:
            if (datetime.now().astimezone()-datetime.fromisoformat(current['fetched_at'])).days < max_age_days:
                return current
        except (KeyError, TypeError, ValueError):
            pass
    try:
        fresh = fetch_season(season, get)
    except Exception as e:
        if current:
            return dict(current, warning='Roster talent refresh failed, using the cached copy: '+str(e))
        raise
    path = data/CACHE_NAME
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(fresh, indent=2), encoding='utf-8')
    temp.replace(path)
    return fresh


def lookup(stored, team_name):
    """The composite row for one school, or None when 247 does not list it."""
    return ((stored or {}).get('schools') or {}).get(key(team_name)) if team_name else None


def leaderboard(stored):
    rows = list(((stored or {}).get('schools') or {}).values())
    return sorted(rows, key=lambda r: (r.get('rank') is None, r.get('rank') or 0, r['team']))


def fit(stored, ratings, names):
    """Least-squares fit of team rating on average player rating.

    Returns None when too few rated teams appear on the composite to say
    anything, leaving the model exactly as it was -- same contract as nil.fit.
    """
    pairs = []
    for team_id, r in ratings.items():
        row = lookup(stored, names.get(team_id, ''))
        if row and row.get('avg_rating') is not None and r.get('rating') is not None:
            pairs.append((row['avg_rating'], r['rating']))
    if len(pairs) < MIN_FIT_TEAMS:
        return None
    mean_x = sum(x for x, _ in pairs)/len(pairs)
    mean_y = sum(y for _, y in pairs)/len(pairs)
    sxx = sum((x-mean_x)**2 for x, _ in pairs)
    if sxx <= 0:
        return None
    slope = sum((x-mean_x)*(y-mean_y) for x, y in pairs)/sxx
    intercept = mean_y-slope*mean_x
    total = sum((y-mean_y)**2 for _, y in pairs)
    residual = sum((y-(intercept+slope*x))**2 for x, y in pairs)
    return {'slope': round(slope, 4), 'intercept': round(intercept, 4), 'teams': len(pairs),
            'r_squared': round(1-residual/total, 4) if total else 0.0}


def weight(season_games):
    """Full weight before a team has played, exactly zero by FADE_GAMES.

    Counted in current-season games only: last season's results are the very
    thing a new roster can make stale.
    """
    if season_games is None or season_games >= FADE_GAMES or MAX_WEIGHT <= 0:
        return 0.0
    return MAX_WEIGHT*(1-season_games/FADE_GAMES)


def implied_rating(fitted, avg_rating):
    return fitted['intercept']+fitted['slope']*avg_rating


def team_shift(fitted, row, rating, season_games):
    """Margin points to move one team toward what its roster implies."""
    w = weight(season_games)
    if not fitted or not row or row.get('avg_rating') is None or rating is None or w <= 0:
        return 0.0
    return round(w*(implied_rating(fitted, row['avg_rating'])-rating), 3)


def margin_shift(fitted, home_row, away_row, home_rating, away_rating, home_games, away_games):
    """Points to move the projected margin, positive toward the home side."""
    if not fitted:
        return 0.0
    return round(team_shift(fitted, home_row, home_rating, home_games)
                 -team_shift(fitted, away_row, away_rating, away_games), 2)
