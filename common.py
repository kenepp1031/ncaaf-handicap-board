"""Shared fetch helpers + constants for the NCAAF handicap batch pipeline.

Ported from feeds.py/power.py's scattered helpers into one place, the same
role NFL 2.0's common.py plays.
"""
from __future__ import annotations

import html
import json
import re
import urllib.request

ESPN = 'https://site.api.espn.com/apis/site/v2/sports/football/college-football/'
CBS = 'https://www.cbssports.com/college-football/rankings/cbs-sports-rankings/'
DK = ('https://dknetwork.draftkings.com/draftkings-sportsbook-betting-splits/'
      '?tb_eg=NCAA+Football&tb_edate=n30days&tb_emt=0&itm_content=NCAA+Football')


def fetch_text(url: str, timeout: int = 25) -> str:
    # No headers, deliberately: ESPN's site.api.espn.com (Akamai-fronted)
    # 403s any request carrying a custom User-Agent, but allows Python's
    # unset/default one. Matches the original feeds.py's bare fetch().
    request = urllib.request.Request(url)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode('utf-8', 'replace')


def fetch_json(url: str, timeout: int = 25) -> dict:
    return json.loads(fetch_text(url, timeout))


def clean(s: str) -> str:
    return ' '.join(html.unescape(re.sub('<[^>]*>', ' ', s)).split())


# Team-name normalization shared across ingest/rating modules — load-bearing:
# every scraped source spells the same school differently.
_ALIASES = {
    'miamifla': 'miami', 'miamifl': 'miami', 'miamioh': 'miamiohio', 'ncstate': 'northcarolinastate',
    'mississippi': 'olemiss', 'southerncalifornia': 'usc', 'pittsburgh': 'pitt',
    'appstate': 'appalachianstate', 'wkentucky': 'westernkentucky', 'nillinois': 'northernillinois',
    'samhoustonstate': 'samhouston', 'connecticut': 'uconn', 'massachusetts': 'umass',
    'sanjsest': 'sanjosestate', 'sanjosest': 'sanjosestate', 'sanjosstate': 'sanjosestate',
    'arizonast': 'arizonastate', 'boisest': 'boisestate',
}


def normal(s: str) -> str:
    s = re.sub('[^a-z0-9]', '', (s or '').lower())
    return _ALIASES.get(s, s)


# CBS's abbreviated school names. FBS membership and FCS pooling both key off
# team *names*, so every comparison against CBS's list goes through fbs_key().
_FBS_ALIASES = dict(zip(
    'missstate ndakotast iowast sandiegost michiganst wmichigan coloradost washingtonst gasouthern jacksonvillest arkansasst appst fresnost texasst utahst kennesawst fau ccarolina fiu newmexicost somiss emichigan cmichigan georgiast sacramentost missourist middletenn kentst ballst sanjosstate'.split(),
    'mississippistate northdakotastate iowastate sandiegostate michiganstate westernmichigan coloradostate washingtonstate georgiasouthern jacksonvillestate arkansasstate appalachianstate fresnostate texasstate utahstate kennesawstate floridaatlantic coastalcarolina floridainternational newmexicostate southernmiss easternmichigan centralmichigan georgiastate sacramentostate missouristate middletennessee kentstate ballstate sanjosestate'.split()))
_FBS_ALIASES.update(fiu='floridainternational', newmexicost='newmexicostate', somiss='southernmiss')


def fbs_key(name: str) -> str:
    key = normal(name)
    return _FBS_ALIASES.get(key, key)


def least_squares(pairs, min_points):
    """Fit y = intercept + slope*x to (x, y) pairs. None when there are too few
    points or no spread in x. Shared by the spending/talent/penalty priors."""
    if len(pairs) < min_points:
        return None
    xs = [x for x, _ in pairs]
    ys = [y for _, y in pairs]
    mean_x, mean_y = sum(xs) / len(xs), sum(ys) / len(ys)
    sxx = sum((x - mean_x) ** 2 for x in xs)
    if sxx <= 0:
        return None
    slope = sum((x - mean_x) * (y - mean_y) for x, y in pairs) / sxx
    intercept = mean_y - slope * mean_x
    total = sum((y - mean_y) ** 2 for y in ys)
    residual = sum((y - (intercept + slope * x)) ** 2 for x, y in pairs)
    return {'slope': round(slope, 4), 'intercept': round(intercept, 4), 'teams': len(pairs),
            'r_squared': round(1 - residual / total, 4) if total else 0.0}


# Combined rank (ESPN Top 25 + RotoBaller top 10/honorable mentions blend) and
# venue name, for the road-game "hostile environment" note. Ported from power.py.
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

# Small, curated set — a structural "same conference" concept doesn't map
# cleanly to CFB the way NFL divisions do, so this stays a short, verified list.
RIVALRIES = {
    frozenset(('kansas', 'missouri')): 'Border Showdown rivalry',
    frozenset(('iowa', 'iowastate')): 'Cy-Hawk rivalry',
}

POOLED_FCS = '_FCS'

STATES = dict(zip(
    'AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY'.split(),
    'Alabama|Alaska|Arizona|Arkansas|California|Colorado|Connecticut|Delaware|Florida|Georgia|Hawaii|Idaho|Illinois|Indiana|Iowa|Kansas|Kentucky|Louisiana|Maine|Maryland|Massachusetts|Michigan|Minnesota|Mississippi|Missouri|Montana|Nebraska|Nevada|New Hampshire|New Jersey|New Mexico|New York|North Carolina|North Dakota|Ohio|Oklahoma|Oregon|Pennsylvania|Rhode Island|South Carolina|South Dakota|Tennessee|Texas|Utah|Vermont|Virginia|Washington|West Virginia|Wisconsin|Wyoming'.split('|')))
