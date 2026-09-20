# College Football Picks

Batch pipeline, matching the architecture of the sibling NFL 2.0 app: run it, it ingests this week's data into a local SQLite database, fits the rating model, and writes one static `dashboard/dashboard.html` that opens in your browser. No live server, no polling, no picks/wager tracker — open the file, read it, close it, run it again next time you want fresh numbers.

The page is one continuous scroll: a short note on how to read it, then every Top-50 matchup in kickoff order, then the power ranking. There is deliberately no ranked pick list — see **Measured accuracy** below. Kickoff times are shown in the time zone of the machine that ran the pipeline, as "1:00 PM Saturday". `streamlit_app.py` is the optional phone view: it embeds the same rendered file on Streamlit Cloud, so refresh it by re-running the pipeline and pushing `dashboard/dashboard.html`.

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

The model lean compares the independent model spread, adjusted for rest/lookahead/letdown notes, with the observed market. Stadium reputation is context only; home advantage is already in the scoring model. Confidence is a qualitative Low/Moderate/High label rating **how much to trust the projection**, not how good a bet is — it falls as the model moves away from the market. It is not a calibrated cover probability.

## Measured accuracy

Walk-forward over the 2025 and 2026 seasons (refit per game-date on prior data only), 786 FBS-vs-FBS games:

| | model | closing line |
|---|---|---|
| margin MAE | 13.07 | **11.83** |
| 2026 only (n=114) | 14.46 | **11.59** |
| correlation with actual margin | 0.609 | **0.691** |

**This model does not beat the closing line.** Its error also grows monotonically with its distance from that line — 10.7 margin MAE where it sits within a point of the market, 17.9 where it is 10+ points away, and 49-61 ATS in the 6-10 point band. Ranking games by model-vs-market disagreement therefore selects for model error, which is why the top-five picks panel and the old "bigger edge = higher confidence" scale were both removed on 2026-09-20.

A sweep of ridge (0.5-15), half-life (90-730) and home advantage (2.0-4.5) put the shipped settings at the MAE minimum, with ATS at a 3+ point threshold near 50% across the entire grid. The gap to the market is structural, not a tuning problem: the model sees only final scores — no possessions, yards, success rate, turnover regression, garbage-time control, or QB/injury information.

## School spending and roster talent

Roster cost (nil-ncaa.com) and 247Sports' Team Talent Composite each feed a light prior on the projected margin, fitted fresh every run from that run's own ratings — never assumed. Both fade to zero once a team has enough current-season games, and are skipped when a side doesn't report a figure. Set `MAX_WEIGHT = 0` in `ratings/nil_prior.py` or `ratings/talent_prior.py` to disable either.

Walk-forward, both measure as roughly neutral (MAE 13.05 and 13.03 respectively against 13.07 with all priors off). The third prior — penalty tendency, in `ratings/officiating_prior.py` — measured actively harmful (MAE 13.16, ATS 50.7% against 52.9%) and was disabled on 2026-09-20 by setting its `MAX_WEIGHT` to 0. Penalty differential is mostly game script and opponent quality rather than a team trait, and it typically fits at an R² near 0.01. Note that all three `fit()` calls regress their variable against the very ratings they then adjust, so the R² reported in the dashboard status line is in-sample against its own target and should not be read as evidence the prior predicts anything.

## Weather

Open-Meteo supplies hourly city forecasts from kickoff through about three hours afterward, up to 16 days out. Outdoor-game banners flag wind/gusts at least 15 mph, rain, snow, and freezing/mixed precipitation. Indoor venues suppress field-weather alerts.

## Data

Everything lives in `ncaaf_handicap.db` (gitignored — regenerate with `--ingest-seasons`, or copy it elsewhere if you want a backup). `db/schema.sql` is the full table definition. ESPN removes the odds from a game once it kicks off, so `ingest/dk_lines.py` archives every observed line into `line_history`; the last capture before kickoff becomes that game's closing line for ATS grading.

`projection_snapshots` is the audit trail: an append-only row per (game, run) written **only before kickoff**, so the record of what was published can never be overwritten by a later run. `projections` remains a single current-view row per game for the dashboard. A finished game never gets a projection written at all — the earlier rule ("keep the first one") let a backfill run freeze hindsight projections in permanently, which left 201 of 205 completed 2026 games both ungradable and un-recomputable until it was fixed on 2026-09-20.

`backtest/log_results.py` grades the last pre-kickoff snapshot against the closing line, scoring `lean_home_spread` — the number the dashboard actually shows — rather than the raw model line. `backtest/report.py` splits the record by edge bucket and by confidence tier, reports the model's margin error beside the closing line's own on the same games, and quarantines pooled-FCS games from the headline (one Oregon 84–0 Portland State supplied 31.5 of the 44.2 total absolute error in the first version of the log). Run `python -m backtest.report --season 2026`.

Run `python -m unittest discover -s ratings` for the rating-engine regression checks. See `CHANGELOG-2026-09-09.md` for the pre-migration app's detailed change history.
