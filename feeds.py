"""Public-source imports with local cache; no account or API key required."""
import json
import re
import html
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlencode

ESPN = 'https://site.api.espn.com/apis/site/v2/sports/football/college-football/'
CBS = 'https://www.cbssports.com/college-football/rankings/cbs-sports-rankings/'
DK = 'https://dknetwork.draftkings.com/draftkings-sportsbook-betting-splits/?tb_eg=NCAA+Football&tb_edate=n30days&tb_emt=0&itm_content=NCAA+Football'


def fetch(url):
    request = urllib.request.Request(url)
    with urllib.request.urlopen(request, timeout=25) as response:
        return response.read().decode('utf-8')


def clean(s):
    return ' '.join(html.unescape(re.sub('<[^>]*>', ' ', s)).split())


def normal(s):
    s = re.sub('[^a-z0-9]', '', s.lower())
    return {'miamifla': 'miami', 'miamifl': 'miami', 'miamioh': 'miamiohio', 'ncstate': 'northcarolinastate',
            'mississippi': 'olemiss', 'southerncalifornia': 'usc', 'pittsburgh': 'pitt',
            'appstate': 'appalachianstate', 'wkentucky': 'westernkentucky', 'nillinois': 'northernillinois',
            'samhoustonstate': 'samhouston', 'connecticut': 'uconn', 'massachusetts': 'umass',
            'sanjsest': 'sanjosestate', 'sanjosest': 'sanjosestate', 'arizonast': 'arizonastate', 'boisest': 'boisestate'}.get(s, s)


def parse_cbs(page):
    ranks = {}
    for row in re.findall(r'<tr class="TableBase-bodyTr".*?</tr>', page, re.S):
        cells = re.findall(r'<td\b[^>]*>(.*?)</td>', row, re.S)
        if len(cells) < 2:
            continue
        team = re.search(r'<span class="TeamName">(.*?)</span>', cells[1], re.S)
        rank = clean(cells[0])
        if team and rank.isdigit():
            ranks[normal(clean(team[1]))] = int(rank)
    if len(ranks) < 50:
        raise ValueError('CBS layout changed or fewer than 50 rankings returned')
    return ranks


def parse_dk(page):
    rows = []
    for block in re.split(r'<div class="tb-se border-', page)[1:]:
        title = re.search(r'<h5\b.*?</h5>', block, re.S)
        when = re.search(r'>(\d{1,2}/\d{1,2}),', block)
        if not title or not when:
            continue
        markets = re.split(r'<div class="tb-se-head\b[^>]*>', block)[1:]
        for market in markets:
            if not clean(market).startswith('Spread '):
                continue
            for side in re.split(r'<div class="tb-sodd\b[^>]*>', market)[1:]:
                label = re.search(r'<div class="tb-slipline[^>]*>(.*?)</div>', side, re.S)
                odds = re.search(r'class="tb-odd-s[^>]*>\s*([^<]+)', side)
                pct = re.findall(r'<div class="flex-1">\s*(\d+(?:\.\d+)?)%', side)
                if not label or not odds or len(pct) < 2:
                    continue
                match = re.fullmatch(r'(.*?)\s+([+−-]\d+(?:\.\d+)?)', clean(label[1]))
                if match:
                    rows.append({'team': normal(match[1]), 'month_day': when[1], 'spread': float(match[2].replace('−', '-')),
                                 'odds': float(clean(odds[1]).replace('−', '-')), 'handle': float(pct[0]), 'bets': float(pct[1])})
    return rows


def number(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_events(data):
    events = []
    for event in data.get('events', []):
        comp = event['competitions'][0]
        sides = {c['homeAway']: c for c in comp['competitors']}
        if 'home' not in sides or 'away' not in sides:
            continue
        dt = datetime.fromisoformat(event['date'].replace('Z', '+00:00')).astimezone()
        status = comp.get('status', event.get('status', {})).get('type', {})
        row = {'id': event['id'], 'game_date': dt.date().isoformat(), 'kickoff': dt.isoformat(),
               'season': event.get('season', {}).get('year'), 'week': event.get('week', {}).get('number'),
               'status': status.get('description', 'Unknown'), 'completed': bool(status.get('completed')),
               'neutral': comp.get('neutralSite', False), 'market_source': '', 'market_observed_at': datetime.now().astimezone().isoformat(timespec='seconds')}
        row['season_type'] = event.get('season', {}).get('type', 2)
        row['venue'] = comp.get('venue', {})
        odds_list = comp.get('odds', [])
        odds = next((o for o in odds_list if o.get('provider', {}).get('name') == 'DraftKings'), odds_list[0] if odds_list else {})
        row['market_source'] = (odds.get('provider', {}).get('name', '')+' via ESPN').strip() if odds else ''
        for side, c in sides.items():
            team = c['team']
            row[side] = team.get('location', team['displayName'])
            row[side+'_id'] = str(team['id'])
            row[side+'_logo'] = team.get('logo', '')
            row[side+'_record'] = next((r.get('summary','') for r in c.get('records',[]) if r.get('type') == 'total'), '')
            row[side+'_rank'] = c.get('curatedRank', {}).get('current', 99)
            row[side+'_score'] = int(c.get('score', 0)) if row['completed'] else None
            closing = odds.get('pointSpread', {}).get(side, {}).get('close', {})
            row[side+'_spread'] = number(closing.get('line'))
            row[side+'_odds'] = number(closing.get('odds'))
        if row['home_spread'] is None:
            raw = number(odds.get('spread'))
            home_favorite = odds.get('homeTeamOdds', {}).get('favorite')
            away_favorite = odds.get('awayTeamOdds', {}).get('favorite')
            if raw is not None and (home_favorite is True or away_favorite is True or raw == 0):
                row['home_spread'] = -abs(raw) if home_favorite else abs(raw)
                row['away_spread'] = -row['home_spread']
        row['odds_status'] = 'Available' if row['home_spread'] is not None else ('Provider supplied no spread' if odds else 'No odds supplied by ESPN')
        row['total'] = number(odds.get('overUnder'))
        events.append(row)
    return events


def composite_teams(events, cbs, ap, coaches):
    teams = {}
    for e in events:
        for side in ('home','away'):
            key = e[side+'_id']
            cr = cbs.get(normal(e[side]))
            ar, ur = ap.get(key), coaches.get(key)
            if cr is None and ar is None and ur is None:
                continue
            scores = []
            for ranks, rank, size in ((cbs,cr,50),(ap,ar,25),(coaches,ur,25)):
                if ranks:
                    scores.append(max(0, (size+1-(rank or size+1))/size))
            teams[key] = dict(id=key, team=e[side], cbs=cr, ap=ar, coaches=ur,
                              score=round(100*sum(scores)/len(scores),6) if scores else 0,
                              logo=e.get(side+'_logo',''))
    ordered = sorted(teams.values(),key=lambda t:(-t['score'],t['cbs'] or 999,t['team']))[:50]
    for i, t in enumerate(ordered,1):
        t['rank'] = i
    return ordered


STATES = dict(zip('AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY'.split(),
    'Alabama|Alaska|Arizona|Arkansas|California|Colorado|Connecticut|Delaware|Florida|Georgia|Hawaii|Idaho|Illinois|Indiana|Iowa|Kansas|Kentucky|Louisiana|Maine|Maryland|Massachusetts|Michigan|Minnesota|Mississippi|Missouri|Montana|Nebraska|Nevada|New Hampshire|New Jersey|New Mexico|New York|North Carolina|North Dakota|Ohio|Oklahoma|Oregon|Pennsylvania|Rhode Island|South Carolina|South Dakota|Tennessee|Texas|Utah|Vermont|Virginia|Washington|West Virginia|Wisconsin|Wyoming'.split('|')))


def add_weather(events, folder, start, end):
    path = folder/'locations.json'
    locations = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    targets = {}
    for e in events:
        if not start <= e['game_date'] <= end or e.get('completed') or e.get('venue',{}).get('indoor'):
            continue
        address = e.get('venue',{}).get('address',{})
        city, state = address.get('city'), address.get('state','')
        country = address.get('country','USA')
        if city:
            targets['|'.join((city,state,country))] = address
    def locate(item):
        key, address = item
        try:
            raw = json.loads(fetch('https://geocoding-api.open-meteo.com/v1/search?'+urlencode({'name':address['city'],'count':20,'language':'en','format':'json'})))
            options = raw.get('results',[])
            country = {'USA':'US','United States':'US','Ireland':'IE','IRL':'IE'}.get(address.get('country'),address.get('country','US'))
            options = [r for r in options if r.get('country_code') == country]
            state = STATES.get(address.get('state'),address.get('state'))
            if state:
                options = [r for r in options if r.get('admin1','').casefold() == state.casefold()]
            if options:
                return key,options[0]
        except Exception:
            pass
        return key,None
    missing = [(k,a) for k,a in targets.items() if k not in locations]
    with ThreadPoolExecutor(max_workers=4) as pool:
        for k,v in pool.map(locate,missing):
            if v:
                locations[k] = v
    path.write_text(json.dumps(locations,indent=2),encoding='utf-8')
    keys = [k for k in targets if k in locations]
    weather = {}
    # Batch nearby-city conditions; this is not a stadium weather-station reading.
    if keys:
        query = {'latitude':','.join(str(locations[k]['latitude']) for k in keys),
                 'longitude':','.join(str(locations[k]['longitude']) for k in keys),
                 'hourly':'temperature_2m,weather_code,wind_speed_10m,wind_gusts_10m,precipitation,rain,snowfall', 'forecast_days':16,
                 'temperature_unit':'fahrenheit','wind_speed_unit':'mph','precipitation_unit':'inch','timezone':'GMT'}
        data = json.loads(fetch('https://api.open-meteo.com/v1/forecast?'+urlencode(query)))
        data = data if isinstance(data,list) else [data]
        for k, item in zip(keys,data):
            weather[k] = item.get('hourly',{})
    for e in events:
        if not start <= e['game_date'] <= end:
            continue
        address=e.get('venue',{}).get('address',{})
        key='|'.join((address.get('city',''),address.get('state',''),address.get('country','USA')))
        e['weather'] = None
        e['weather_status'] = 'Forecast unavailable or outside the 16-day window'
        if e.get('venue',{}).get('indoor'):
            e['weather_status'] = 'Indoor venue — weather does not affect field conditions'
            continue
        hourly = weather.get(key, {})
        kickoff = datetime.fromisoformat(e['kickoff']).astimezone(timezone.utc).replace(tzinfo=None)
        indices = [i for i,t in enumerate(hourly.get('time',[])) if kickoff.replace(minute=0,second=0,microsecond=0) <= datetime.fromisoformat(t) <= kickoff+timedelta(hours=3)]
        if indices and not e.get('completed'):
            w = {k: max((hourly[k][i] for i in indices if hourly[k][i] is not None), default=None) for k in ('wind_speed_10m','wind_gusts_10m','precipitation','rain','snowfall')}
            w.update(temperature_2m=hourly['temperature_2m'][indices[0]], weather_code=hourly['weather_code'][indices[0]],
                     weather_codes=[hourly['weather_code'][i] for i in indices], time=hourly['time'][indices[0]],
                     forecast=True, location=address.get('city',''), source='Open-Meteo', fetched_at=datetime.now(timezone.utc).isoformat())
            e['weather'] = w
            e['weather_status'] = 'Kickoff through approximately 3 hours after kickoff'

    return len(weather),len(targets)


def refresh(folder, week_start, full_season=False, week_end=None):
    folder = Path(folder)
    folder.mkdir(exist_ok=True)
    cache = folder/'live.json'
    previous = json.loads(cache.read_text(encoding='utf-8')) if cache.exists() else {}
    warnings = []
    season = week_start.year if week_start.month >= 7 else week_start.year-1
    events = {r['id']: r for r in previous.get('events', []) if r.get('season') == season}
    if full_season or previous.get('season') != season:
        start, end = f'{season}0801', f'{season+1}0201'
    else:
        start, end = week_start.strftime('%Y%m%d'), (week_end or week_start+timedelta(days=6)).strftime('%Y%m%d')
    url = ESPN+f'scoreboard?limit=1000&groups=80&dates={start}-{end}'
    data = json.loads(fetch(url))
    imported = parse_events(data)
    if not imported:
        raise ValueError('ESPN returned no games; existing saved data was retained')
    for r in imported:
        events[r['id']] = r
    cbs = previous.get('cbs', {})
    try:
        cbs = parse_cbs(fetch(CBS))
    except Exception as e:
        warnings.append('CBS refresh failed; retained prior ranking snapshot: '+str(e))
    ap = previous.get('ap', {})
    ap_date = previous.get('ap_date', '')
    coaches = previous.get('coaches', {})
    try:
        rankings = json.loads(fetch(ESPN+'rankings'))
        poll = next(r for r in rankings['rankings'] if r.get('type') == 'ap')
        ap = {str(r['team']['id']): r['current'] for r in poll['ranks']}
        ap_date = poll.get('date', '')
        coaches_poll = next((r for r in rankings['rankings'] if r.get('type') == 'usa'), None)
        if coaches_poll:
            coaches = {str(r['team']['id']):r['current'] for r in coaches_poll['ranks'] if r['current']<=25}
    except Exception as e:
        warnings.append('AP via ESPN refresh failed; retained prior snapshot: '+str(e))
    split_rows = []
    try:
        first = fetch(DK)
        split_rows.extend(parse_dk(first))
        pages = [int(x) for x in re.findall(r'tb_page=(\d+)', first)]
        for page in range(2, min(max(pages, default=1), 20)+1):
            split_rows.extend(parse_dk(fetch(DK+f'&tb_page={page}')))
        if not split_rows:
            warnings.append('DraftKings supplied no readable spread splits; sportsbook lines from ESPN remain available.')
    except Exception as e:
        warnings.append('DraftKings splits refresh failed: '+str(e))
    split_map = {(r['team'], r['month_day']): r for r in split_rows}
    now = datetime.now().astimezone().isoformat(timespec='seconds')
    top50 = composite_teams(events.values(),cbs,ap,coaches)
    combined = {t['id']:t['rank'] for t in top50}
    for r in events.values():
        day = date.fromisoformat(r['game_date'])
        for side in ('home', 'away'):
            r[side+'_ap'] = ap.get(r[side+'_id'])
            r[side+'_cbs'] = cbs.get(normal(r[side]))
            r[side+'_combined'] = combined.get(r[side+'_id'])
            split = split_map.get((normal(r[side]), f'{day.month}/{day.day}')) if day >= date.today() else None
            r.pop(side+'_splits', None)
            if split and not r['completed']:
                r[side+'_splits'] = split
                r[side+'_spread'], r[side+'_odds'] = split['spread'], split['odds']
                r['odds_status'] = 'Available'
                r['market_source'] = 'DraftKings Network'
                r['market_observed_at'] = now
    weeks = []
    calendar = data.get('leagues',[{}])[0].get('calendar',[])
    if not any(isinstance(p,dict) and p.get('entries') for p in calendar):
        try:
            calendar_data = json.loads(fetch(ESPN+'scoreboard'))
            calendar = calendar_data.get('leagues',[{}])[0].get('calendar',[]) if calendar_data.get('season',{}).get('year')==season else []
        except Exception as e:
            warnings.append('Week calendar refresh failed: '+str(e))
    for period in calendar:
        if not isinstance(period,dict):
            continue
        if int(period.get('value',0)) not in (2,3):
            continue
        for entry in period.get('entries',[]):
            weeks.append({'id':str(period['value'])+':'+str(entry['value']), 'type':int(period['value']),
                'number':int(entry['value']), 'label':entry['label'] if int(period['value'])==2 else period['label']+' '+entry['label'],
                'start':entry['startDate'],'end':entry['endDate'],'detail':entry.get('detail','')})
    try:
        count,total = add_weather(list(events.values()),folder,week_start.isoformat(),(week_end or week_start+timedelta(days=6)).isoformat())
        if count<total:
            warnings.append(f'Weather available for {count}/{total} venue cities; missing locations are marked unavailable.')
    except Exception as e:
        warnings.append('Weather refresh failed: '+str(e))
        for r in imported:
            r['weather'] = None
    history_path = folder/f'history-{season-1}.json'
    history_events = []
    try:
        if history_path.exists():
            history_events = json.loads(history_path.read_text(encoding='utf-8'))
        else:
            history_data = json.loads(fetch(ESPN+f'scoreboard?limit=1000&groups=80&dates={season-1}0801-{season}0201'))
            history_events = [e for e in parse_events(history_data) if e.get('completed') and e.get('season') == season-1]
            if history_events:
                history_path.write_text(json.dumps(history_events),encoding='utf-8')
    except Exception as e:
        warnings.append('Previous-season scoring history unavailable: '+str(e))
    result = {'history_events':history_events, 'season': season, 'updated_at': now, 'ap_date': ap_date, 'cbs': cbs, 'ap': ap, 'coaches':coaches,'top50':top50,'weeks':weeks or previous.get('weeks',[]),
              'events': sorted(events.values(), key=lambda r: r['kickoff']), 'warnings': warnings,
              'imported_count': len(imported), 'splits_count': len(split_rows)}
    temp = cache.with_suffix('.tmp')
    temp.write_text(json.dumps(result, indent=2), encoding='utf-8')
    temp.replace(cache)
    return result


if __name__ == '__main__':
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument('--full-season', action='store_true')
    a = p.parse_args()
    today = date.today()
    result = refresh(Path(__file__).parent/'data', today-timedelta(days=today.weekday()), a.full_season)
    print(json.dumps({k: result[k] for k in ('season', 'updated_at', 'imported_count', 'splits_count', 'warnings')}, indent=2))
