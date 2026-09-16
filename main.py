"""NCAAF handicap weekly pipeline entrypoint. Batch-pipeline architecture
matching NFL 2.0's main.py: ingest -> ratings -> backtest -> render, run
once and open the resulting static dashboard.html.

Usage:
    python main.py                          Auto-detects season/week from
                                             today's date and runs the pipeline
    python main.py --week 3                 Normal weekly run for the current season
    python main.py --season 2026 --week 3   Explicit season/week
    python main.py --skip-scrape            Re-run ratings/render only, no network calls
    python main.py --no-open                Don't open the dashboard in a browser
"""
from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from db.db import init_db, connect
from ingest import espn_scoreboard, rankings, cbs_odds, dk_lines, weather as weather_ingest
from ingest import nil_spending, talent as talent_ingest, officiating as officiating_ingest
from ratings import power
from backtest.log_results import log_season
from dashboard.render import render_week


def current_season_week(today: date | None = None) -> tuple[int, int]:
    """(season, week) for today's date. CFB's regular season kicks off the
    last Saturday of August; roll back a year before that, and once games
    exist in the DB, prefer advancing the moment a week's games are all
    final rather than waiting on a fixed date window."""
    today = today or date.today()
    season = today.year if today.month >= 7 else today.year - 1

    with connect() as con:
        rows = con.execute(
            """SELECT week, SUM(home_score IS NULL) AS unplayed FROM games
               WHERE season=? AND week_type=2 GROUP BY week ORDER BY week""",
            (season,)).fetchall()

    for r in rows:
        if r['unplayed'] > 0:
            return season, r['week']
    if rows:
        return season, rows[-1]['week'] + 1

    # No games ingested yet for this season: fall back to a date-based guess
    # (late-August anchor), refined once the first scoreboard pull lands.
    season_start = date(season, 8, 24)
    week = max(1, (today - season_start).days // 7 + 1)
    return season, week


def backfill(seasons: list[int]) -> None:
    print(f'Backfilling seasons {seasons}...')
    for season in seasons:
        print(f'  {season}: scoreboard...')
        espn_scoreboard.ingest(season, full_season=True)
        print(f'  {season}: rankings...')
        try:
            rankings.ingest(season)
        except Exception as e:
            print(f'  {season}: rankings failed ({e})')


def weekly_run(season: int, week: int, skip_scrape: bool = False) -> Path:
    if not skip_scrape:
        print('Refreshing schedule/lines/rankings/weather/priors...')
        today = date.today()
        week_start = today - timedelta(days=today.weekday())
        try:
            # Start a week back so an early-week run picks up last weekend's finals for the ratings fit.
            espn_scoreboard.ingest(season, week_start - timedelta(days=7), week_start + timedelta(days=6))
        except Exception as e:
            print(f'  scoreboard refresh failed: {e}')
        try:
            rankings.ingest(season)
        except Exception as e:
            print(f'  rankings refresh failed: {e}')
        try:
            cbs_odds.ingest(season)
        except Exception as e:
            print(f'  CBS closing lines refresh failed: {e}')
        try:
            dk_lines.ingest()
        except Exception as e:
            print(f'  DK lines refresh failed: {e}')
        try:
            weather_ingest.refresh_week(week_start.isoformat(), (week_start + timedelta(days=6)).isoformat())
        except Exception as e:
            print(f'  weather refresh failed: {e}')
        try:
            nil_spending.ingest(season)
        except Exception as e:
            print(f'  spending refresh failed: {e}')
        try:
            talent_ingest.ingest(season)
        except Exception as e:
            print(f'  talent refresh failed: {e}')
        try:
            officiating_ingest.ingest()
        except Exception as e:
            print(f'  officiating refresh failed: {e}')

    print('Fitting ratings model...')
    result = power.build(season, date.today())
    print(f"  {result['status']}")

    log_season(season)
    return render_week(season, week)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='NCAAF handicap weekly pipeline')
    parser.add_argument('--week', type=int, help='Week number to project/render (default: auto-detected)')
    parser.add_argument('--season', type=int, help='Season year (default: auto-detected)')
    parser.add_argument('--ingest-seasons', type=str, help='Comma-separated seasons to backfill, e.g. 2024,2025,2026')
    parser.add_argument('--skip-scrape', action='store_true', help='Skip network refresh, just re-rate/render')
    parser.add_argument('--no-open', action='store_true', help="Don't open the dashboard in a browser")
    args = parser.parse_args()

    init_db()

    if args.ingest_seasons:
        backfill([int(s) for s in args.ingest_seasons.split(',')])

    if args.week or not args.ingest_seasons:
        auto_season, auto_week = current_season_week()
        season = args.season or auto_season
        week = args.week or auto_week
        path = weekly_run(season, week, skip_scrape=args.skip_scrape)
        print(f'Dashboard ready: {path}')
        if not args.no_open:
            import webbrowser
            webbrowser.open(path.as_uri())
