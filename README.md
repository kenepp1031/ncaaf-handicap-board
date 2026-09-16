# College Football Picks

Batch pipeline, matching the architecture of the sibling NFL 2.0 app: run it, it ingests this week's data into a local SQLite database, fits the rating model, and writes one static `dashboard/dashboard.html` that opens in your browser. No live server, no polling, no picks/wager tracker — open the file, read it, close it, run it again next time you want fresh numbers.

## Running it

Double-click `Start NCAAF Handicap.cmd`, or from a terminal:

```
python main.py                          # auto-detects season/week from today's date
python main.py --week 3                 # explicit week, current season
python main.py --season 2026 --week 3   # explicit season and week
python main.py --skip-scrape            # re-fit/re-render only, no network calls
python main.py --no-open                # don't open the dashboard in a browser
python main.py --ingest-seasons 2024,2025,2026   # one-time historical backfill
```

Each run: pulls the ESPN scoreboard/schedule, CBS/AP/Coaches rankings, DraftKings betting splits and lines, Open-Meteo weather, school-spending and 247Sports talent figures, and team-level penalty tendencies; fits the rating model on everything completed so far; writes projections, notes and power ratings to `ncaaf_handicap.db`; grades last week's completed games into the backtest log; and renders `dashboard/dashboard.html`.

## Model and rankings

Opponent-adjusted offense and defense are fitted to scoring results from the current and previous season with a 365-day recency half-life and light ridge regularization (1.5), chosen by walk-forward testing. `ratings/handicap_model.py` holds the rating engine itself — dependency-free, unchanged from the pre-migration app, and still usable standalone via its `ratings`/`predict`/`backtest` CLI over CSV files.

Every FCS opponent shares one pooled rating rather than carrying its own — an FCS school appears in one or two FBS results a season, and ridge shrinkage pulls a coefficient built from that little evidence too far toward the mean. The pooled entity is backed by every FCS-vs-FBS game. Without CBS's membership list there is nothing to pool against, so every team keeps its own identity.

The model lean compares the independent model spread, adjusted for rest/lookahead/letdown notes, with the observed market. Stadium reputation is context only; home advantage is already in the scoring model. Confidence is a qualitative Low/Moderate/High label, not a calibrated cover probability.

## School spending and roster talent

Roster cost (nil-ncaa.com) and 247Sports' Team Talent Composite each feed a light prior on the projected margin, fitted fresh every run from that run's own ratings — never assumed. Both fade to zero once a team has enough current-season games, and are skipped when a side doesn't report a figure. Set `MAX_WEIGHT = 0` in `ratings/nil_prior.py` or `ratings/talent_prior.py` to disable either.

## Weather

Open-Meteo supplies hourly city forecasts from kickoff through about three hours afterward, up to 16 days out. Outdoor-game banners flag wind/gusts at least 15 mph, rain, snow, and freezing/mixed precipitation. Indoor venues suppress field-weather alerts.

## Data

Everything lives in `ncaaf_handicap.db` (gitignored — regenerate with `--ingest-seasons`, or copy it elsewhere if you want a backup). `db/schema.sql` is the full table definition. ESPN removes the odds from a game once it kicks off, so `ingest/dk_lines.py` archives every observed line into `line_history`; the last capture before kickoff becomes that game's closing line for ATS grading.

`backtest/log_results.py` grades completed games against their closing line; `backtest/report.py` and `backtest/calibration.py` summarize the results (`python -m backtest.report --season 2026`).

Run `python -m unittest discover` for regression checks. See `CHANGELOG-2026-09-09.md` for the pre-migration app's detailed change history.
