"""Open-Meteo weather ingest for outdoor venues in the current date window.

Ported from feeds.py's add_weather(). Uses a dynamic per-city geocode cache
(`geocode_cache` table, replacing data/locations.json) rather than a static
stadium table — CFB has 130+ campuses across many towns Open-Meteo must
resolve at runtime, unlike NFL's fixed 32-stadium list.
"""
from __future__ import annotations

import json
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common import STATES, fetch_text
from db.db import connect


def _geocode_lookup(con, city, state, country):
    row = con.execute(
        'SELECT latitude, longitude FROM geocode_cache WHERE city=? AND state=? AND country=?',
        (city, state or '', country or 'USA')).fetchone()
    return (row['latitude'], row['longitude']) if row else None


def _geocode_save(con, city, state, country, lat, lon, admin1, country_code):
    con.execute(
        """INSERT INTO geocode_cache (city, state, country, latitude, longitude, admin1, country_code)
           VALUES (?,?,?,?,?,?,?)
           ON CONFLICT(city, state, country) DO UPDATE SET
               latitude=excluded.latitude, longitude=excluded.longitude,
               admin1=excluded.admin1, country_code=excluded.country_code""",
        (city, state or '', country or 'USA', lat, lon, admin1, country_code))


def _locate(address):
    try:
        raw = json.loads(fetch_text('https://geocoding-api.open-meteo.com/v1/search?' +
                                     urlencode({'name': address['city'], 'count': 20, 'language': 'en', 'format': 'json'})))
        options = raw.get('results', [])
        country = {'USA': 'US', 'United States': 'US', 'Ireland': 'IE', 'IRL': 'IE'}.get(address.get('country'), address.get('country', 'US'))
        options = [r for r in options if r.get('country_code') == country]
        state = STATES.get(address.get('state'), address.get('state'))
        if state:
            options = [r for r in options if r.get('admin1', '').casefold() == state.casefold()]
        return options[0] if options else None
    except Exception:
        return None


def refresh_week(start: str, end: str) -> dict:
    """start/end: ISO date strings for the outdoor games to forecast."""
    with connect() as con:
        rows = con.execute(
            """SELECT game_id, game_date, kickoff, completed, venue_json FROM games
               WHERE game_date BETWEEN ? AND ?""", (start, end)).fetchall()
        targets = {}   # game_id -> address dict
        for r in rows:
            if r['completed']:
                continue
            venue = json.loads(r['venue_json'] or '{}')
            if venue.get('indoor'):
                con.execute(
                    """INSERT INTO weather (game_id, status, checked_at) VALUES (?,?,?)
                       ON CONFLICT(game_id) DO UPDATE SET status=excluded.status, checked_at=excluded.checked_at""",
                    (r['game_id'], 'Indoor venue — weather does not affect field conditions',
                     datetime.now(timezone.utc).isoformat()))
                continue
            address = venue.get('address', {})
            if address.get('city'):
                targets[r['game_id']] = (r, address)

        missing_keys = {}
        for game_id, (r, address) in targets.items():
            key = (address.get('city', ''), address.get('state', ''), address.get('country', 'USA'))
            if _geocode_lookup(con, *key) is None:
                missing_keys[key] = address
        if missing_keys:
            with ThreadPoolExecutor(max_workers=4) as pool:
                for (key, coords) in zip(missing_keys, pool.map(_locate, missing_keys.values())):
                    if coords:
                        _geocode_save(con, *key, coords['latitude'], coords['longitude'],
                                      coords.get('admin1'), coords.get('country_code'))
            con.commit()

        keys = []
        coords_by_key = {}
        for game_id, (r, address) in targets.items():
            key = (address.get('city', ''), address.get('state', ''), address.get('country', 'USA'))
            latlon = _geocode_lookup(con, *key)
            if latlon and latlon[0] is not None:
                coords_by_key[key] = latlon
                if key not in keys:
                    keys.append(key)

        hourly_by_key = {}
        if keys:
            query = {'latitude': ','.join(str(coords_by_key[k][0]) for k in keys),
                     'longitude': ','.join(str(coords_by_key[k][1]) for k in keys),
                     'hourly': 'temperature_2m,weather_code,wind_speed_10m,wind_gusts_10m,precipitation,rain,snowfall',
                     'forecast_days': 16, 'temperature_unit': 'fahrenheit', 'wind_speed_unit': 'mph',
                     'precipitation_unit': 'inch', 'timezone': 'GMT'}
            data = json.loads(fetch_text('https://api.open-meteo.com/v1/forecast?' + urlencode(query)))
            data = data if isinstance(data, list) else [data]
            for k, item in zip(keys, data):
                hourly_by_key[k] = item.get('hourly', {})

        n_forecast = 0
        for game_id, (r, address) in targets.items():
            key = (address.get('city', ''), address.get('state', ''), address.get('country', 'USA'))
            hourly = hourly_by_key.get(key, {})
            kickoff = datetime.fromisoformat(r['kickoff']).astimezone(timezone.utc).replace(tzinfo=None)
            indices = [i for i, t in enumerate(hourly.get('time', []))
                       if kickoff.replace(minute=0, second=0, microsecond=0) <= datetime.fromisoformat(t) <= kickoff + timedelta(hours=3)]
            checked_at = datetime.now(timezone.utc).isoformat()
            if indices:
                w = {k2: max((hourly[k2][i] for i in indices if hourly[k2][i] is not None), default=None)
                     for k2 in ('wind_speed_10m', 'wind_gusts_10m', 'precipitation', 'rain', 'snowfall')}
                codes = [hourly['weather_code'][i] for i in indices]
                con.execute(
                    """INSERT INTO weather (game_id, temp_f, wind_mph, wind_gusts_mph, precip_in, rain_in, snowfall_in,
                            weather_code, weather_codes_json, forecast_time, status, checked_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                       ON CONFLICT(game_id) DO UPDATE SET
                           temp_f=excluded.temp_f, wind_mph=excluded.wind_mph, wind_gusts_mph=excluded.wind_gusts_mph,
                           precip_in=excluded.precip_in, rain_in=excluded.rain_in, snowfall_in=excluded.snowfall_in,
                           weather_code=excluded.weather_code, weather_codes_json=excluded.weather_codes_json,
                           forecast_time=excluded.forecast_time, status=excluded.status, checked_at=excluded.checked_at""",
                    (game_id, hourly['temperature_2m'][indices[0]], w['wind_speed_10m'], w['wind_gusts_10m'],
                     w['precipitation'], w['rain'], w['snowfall'], hourly['weather_code'][indices[0]],
                     json.dumps(codes), hourly['time'][indices[0]], 'Kickoff through approximately 3 hours after kickoff', checked_at))
                n_forecast += 1
            else:
                con.execute(
                    """INSERT INTO weather (game_id, status, checked_at) VALUES (?,?,?)
                       ON CONFLICT(game_id) DO UPDATE SET status=excluded.status, checked_at=excluded.checked_at""",
                    (game_id, 'Forecast unavailable or outside the 16-day window', checked_at))
        con.commit()
    return {'targets': len(targets), 'forecast': n_forecast}


if __name__ == '__main__':
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument('start')
    p.add_argument('end')
    a = p.parse_args()
    print(refresh_week(a.start, a.end))
