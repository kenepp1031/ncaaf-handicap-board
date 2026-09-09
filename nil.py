"""School spending figures, and a spend-based early-season prior on team strength.

Two tables are read from nil-ncaa.com: estimated 2026 roster cost for Power 4
football programs (what the schools actually pay players), and athletic
department operating expenses for every NCAA I school. Roster cost is the NIL
number; expenses are kept for coverage and context only.

Why spending is a prior rather than a term in the spread
-------------------------------------------------------
Roster spending is not independent information once games have been played: the
scoring model already measures how good a team is, and the market already knows
what each roster cost. Adding a fixed points-per-dollar bump on top would double
count, and no such coefficient has been validated here.

What spending *can* do is stand in for talent before results exist, which is the
one place the model is genuinely weak. So the points-per-dollar slope is not
guessed — it is fitted each refresh from this season's own ratings (rating
regressed on log spending). If spending does not track the ratings, the slope
comes out near zero and the adjustment disappears on its own. The adjustment is
then weighted by how little the model knows about that team, fading linearly to
exactly zero once a team has FADE_GAMES results. It moves the margin only; the
projected total is untouched.

Because the prior works by shrinking a team toward the line, it only behaves
where the line describes that team. Fitted across FBS and FCS together it does
not, so only roster cost — one homogeneous Power 4 population — feeds a
projection. Athletic department expenses are collected and displayed for every
school but never adjust a spread. See MODEL_MEASURES.

Set MAX_WEIGHT to 0 to turn the whole prior off and leave the model unchanged.
"""
import json
import math
import re
import urllib.request
from datetime import date, datetime

from feeds import clean, normal

SOURCE = 'https://nil-ncaa.com/'
CACHE_NAME = 'nil.json'
AGENT = {'User-Agent': 'Mozilla/5.0 (compatible; cfb-handicap/1.0)'}

# Weight given to the spending prior for a team with no games yet, fading to
# zero over FADE_GAMES results. At least MIN_FIT_TEAMS schools must have both a
# rating and a spending figure before any slope is trusted.
MAX_WEIGHT = 0.35
FADE_GAMES = 8
MIN_FIT_TEAMS = 20

# Spending measures in preference order: (cache key, field name on a spending dict).
MEASURES = (('roster', 'roster_cost'), ('expenses', 'athletic_expenses'))

# Measures the *model* may use. Roster cost only, and deliberately so: the
# expense fit spans FBS and FCS, and a single log-linear line through that
# population puts a Power 4 host only ~3 points above an FCS visitor where the
# ratings say 11 and the market says 56. Shrinking toward a line that flat makes
# those projections worse, so expenses stay a display figure. Roster cost is
# fitted on one homogeneous Power 4 population and behaves.
MODEL_MEASURES = (('roster', 'roster_cost'),)

# Two Division I schools answer to the same plain name; the conference column
# separates Miami (FL) from Miami (OH), whose row would otherwise overwrite it.
CONFERENCE_KEYS = {('miami', 'MAC'): 'miamiohio'}

# nil-ncaa uses formal school names where the scoreboard uses the common one.
ALIASES = {'louisianastate': 'lsu', 'southerncal': 'usc', 'southerncalifornia': 'usc',
           'brighamyoung': 'byu', 'texaschristian': 'tcu', 'southernmethodist': 'smu',
           'centralflorida': 'ucf', 'southernmississippi': 'southernmiss',
           'louisianamonroe': 'ullmonroe', 'louisianalafayette': 'louisiana',
           'floridainternational': 'fiu', 'floridaatlantic': 'fau',
           'texasarlington': 'uta', 'alabamabirmingham': 'uab', 'texassanantonio': 'utsa',
           'texaselpaso': 'utep', 'nevadalasvegas': 'unlv', 'miamiflorida': 'miami',
           'mississippi': 'olemiss', 'nicholls': 'nichollsstate'}


def key(name):
    plain = normal(re.sub(r'\s*[-–]\s*', ' ', name or ''))
    return ALIASES.get(plain, plain)


def _money(cell):
    digits = re.sub(r'[^0-9]', '', cell or '')
    return int(digits) if digits else None


def _tables(page):
    for table in re.findall(r'<table.*?</table>', page, re.S):
        rows = []
        for row in re.findall(r'<tr.*?</tr>', table, re.S):
            cells = [clean(c) for c in re.findall(r'<t[dh][^>]*>(.*?)</t[dh]>', row, re.S)]
            if any(cells):
                rows.append(cells)
        if rows:
            yield rows


def parse(page):
    """Pull roster cost and athletic department expenses out of the source page."""
    roster, expenses, names, labels = {}, {}, {}, {}
    for rows in _tables(page):
        header = rows[0]
        title = header[0] if header else ''
        # The per-school roster table is the one broken out by conference; a
        # second table on the page gives conference medians under a similar title.
        if 'Roster Cost' in title and len(header) >= 3 and header[1] == 'Conference':
            labels['roster'] = title.replace('*', '').strip()
            for row in rows[1:]:
                amount = _money(row[2]) if len(row) >= 3 else None
                if row[0] and amount:
                    roster[key(row[0])] = amount
                    names.setdefault(key(row[0]), row[0])
        elif 'Annual Expenses' in title and len(header) >= 6:
            # Column 5 is the most recent year on the page; keep its own heading
            # so the label never drifts from the figures it describes.
            labels['expenses'] = title.replace('*', '').strip()+' — '+header[5].replace('($)', '').strip()
            for row in rows[1:]:
                if len(row) < 6 or row[2] not in ('FBS', 'FCS'):
                    continue
                amount = _money(row[5])
                if not row[0] or not amount:
                    continue
                k = CONFERENCE_KEYS.get((key(row[0]), row[3]), key(row[0]))
                # Rows arrive by spending rank; keep the first so an unforeseen
                # duplicate name cannot quietly replace the larger program.
                expenses.setdefault(k, amount)
                names.setdefault(k, row[0] if k == key(row[0]) else f'{row[0]} ({row[3]})')
    if not roster and not expenses:
        raise ValueError('No spending tables found on the source page')
    return {'source': SOURCE, 'fetched_at': datetime.now().astimezone().isoformat(timespec='seconds'),
            'labels': labels, 'roster': roster, 'expenses': expenses, 'names': names}


def load(data):
    path = data/CACHE_NAME
    try:
        stored = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}
    return stored if isinstance(stored, dict) else {}


def refresh(data, force=False, max_age_days=7):
    """Fetch the spending tables, keeping the cached copy when the site is unreachable."""
    stored = load(data)
    if not force and stored.get('fetched_at'):
        try:
            age = (datetime.now().astimezone()-datetime.fromisoformat(stored['fetched_at'])).days
            if age < max_age_days:
                return stored
        except ValueError:
            pass
    try:
        request = urllib.request.Request(SOURCE, headers=AGENT)
        with urllib.request.urlopen(request, timeout=45) as response:
            page = response.read().decode('utf-8', 'replace')
        fresh = parse(page)
    except Exception as e:
        if stored:
            stored = dict(stored, warning='Spending refresh failed, using the cached copy: '+str(e))
            return stored
        raise
    path = data/CACHE_NAME
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(fresh, indent=2), encoding='utf-8')
    temp.replace(path)
    return fresh


def spending(stored, team_name):
    """Roster cost and athletic department expenses for one school, either may be None."""
    k = key(team_name)
    return {'roster_cost': (stored.get('roster') or {}).get(k),
            'athletic_expenses': (stored.get('expenses') or {}).get(k)}


def _least_squares(pairs):
    if len(pairs) < MIN_FIT_TEAMS:
        return None
    xs = [x for x, _ in pairs]
    ys = [y for _, y in pairs]
    mean_x, mean_y = sum(xs)/len(xs), sum(ys)/len(ys)
    sxx = sum((x-mean_x)**2 for x in xs)
    if sxx <= 0:
        return None
    slope = sum((x-mean_x)*(y-mean_y) for x, y in pairs)/sxx
    intercept = mean_y-slope*mean_x
    total = sum((y-mean_y)**2 for y in ys)
    residual = sum((y-(intercept+slope*x))**2 for x, y in pairs)
    return {'slope': round(slope, 4), 'intercept': round(intercept, 4), 'teams': len(pairs),
            'r_squared': round(1-residual/total, 4) if total else 0.0,
            'points_per_doubling': round(slope*math.log(2), 2)}


def fit(stored, ratings, names):
    """Fit rating against log spending, once per measure.

    Both fits are reported so the Data health panel can show how well spending
    tracks results, but only the measures in MODEL_MEASURES reach a projection.

    Returns None when no measure has enough overlap to say anything, leaving
    the model exactly as it was.
    """
    fits = {}
    for measure, field in MEASURES:
        table = stored.get(measure) or {}
        pairs = []
        for team_id, r in ratings.items():
            dollars = table.get(key(names.get(team_id, '')))
            if dollars and dollars > 0 and r.get('rating') is not None:
                pairs.append((math.log(dollars), r['rating']))
        fitted = _least_squares(pairs)
        if fitted:
            fits[measure] = fitted
    return fits or None


def weight(season_games):
    """How much to trust spending over results: full early, exactly zero by FADE_GAMES.

    Counted in *current-season* games only. The rating fit also draws on last
    season, but a roster turns over between seasons and this year's spending is
    precisely what those old results cannot see.
    """
    if season_games is None or season_games >= FADE_GAMES or MAX_WEIGHT <= 0:
        return 0.0
    return MAX_WEIGHT*(1-season_games/FADE_GAMES)


def implied_rating(fitted, dollars):
    return fitted['intercept']+fitted['slope']*math.log(dollars)


def team_shift(fitted, dollars, rating, season_games):
    """Margin points to move one team toward what its spending implies."""
    w = weight(season_games)
    if not fitted or not dollars or dollars <= 0 or rating is None or w <= 0:
        return 0.0
    return round(w*(implied_rating(fitted, dollars)-rating), 3)


def shared_measure(fits, home_spend, away_spend):
    """The best-quality spending measure that *both* schools report.

    A roster cost and a whole athletic department budget are different scales
    fitted by different regressions, so comparing one against the other reads a
    mid-tier Power 4 payroll as smaller than an FCS school's entire budget.
    Both sides use one measure or the prior sits out — see MODEL_MEASURES for
    why that currently means roster cost or nothing.
    """
    for measure, field in MODEL_MEASURES:
        if fits and fits.get(measure) and (home_spend or {}).get(field) and (away_spend or {}).get(field):
            return measure, field
    return None, None


def margin_shift(fits, home_spend, away_spend, home_rating, away_rating, home_games, away_games):
    """Points to move the projected margin, positive toward the home side."""
    measure, field = shared_measure(fits, home_spend, away_spend)
    if not measure:
        return 0.0, None
    fitted = fits[measure]
    home = team_shift(fitted, home_spend[field], home_rating, home_games)
    away = team_shift(fitted, away_spend[field], away_rating, away_games)
    return round(home-away, 2), measure


def leaderboard(stored, limit=None):
    """Schools ordered by roster cost, then by athletic department expenses."""
    roster, expenses, names = (stored.get(k) or {} for k in ('roster', 'expenses', 'names'))
    rows = []
    for k in set(roster) | set(expenses):
        rows.append({'key': k, 'school': names.get(k, k), 'roster_cost': roster.get(k),
                     'athletic_expenses': expenses.get(k)})
    rows.sort(key=lambda r: (r['roster_cost'] is None, -(r['roster_cost'] or 0),
                             -(r['athletic_expenses'] or 0), r['school']))
    for i, row in enumerate(rows, 1):
        row['spend_rank'] = i
    return rows[:limit] if limit else rows


if __name__ == '__main__':
    from pathlib import Path
    folder = Path(__file__).resolve().parent/'data'
    folder.mkdir(exist_ok=True)
    data = refresh(folder, force=True)
    print(json.dumps({'fetched_at': data['fetched_at'], 'labels': data['labels'],
                      'roster_schools': len(data['roster']), 'expense_schools': len(data['expenses']),
                      'top': [(r['school'], r['roster_cost']) for r in leaderboard(data, 5)]}, indent=2))
